import imaplib
import smtplib
import email
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Optional
from pathlib import Path

from core.plugin import BasePlugin, logger
from core.plugin.plugin_registry import register
from core.utils.tool_utils import BaseTool


_imap_host: str = ""
_imap_port: int = 993
_smtp_host: str = ""
_smtp_port: int = 465
_email_user: str = ""
_email_pass: str = ""
_use_ssl: bool = True


def _decode_mime_header(header_value: str) -> str:
    """解码MIME邮件头"""
    if not header_value:
        return ""
    decoded_parts = decode_header(header_value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                result.append(part.decode("utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _get_email_body(msg: email.message.Message, max_length: int = 10000) -> str:
    """提取邮件正文内容"""
    if msg.is_multipart():
        text_content = ""
        html_content = ""
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                try:
                    text_content = part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    text_content = str(part.get_payload(decode=True))
            elif content_type == "text/html":
                charset = part.get_content_charset() or "utf-8"
                try:
                    html_content = part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    html_content = str(part.get_payload(decode=True))
        body = text_content or html_content or ""
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            body = str(msg.get_payload(decode=True))
    return body[:max_length]


def _get_attachments_info(msg: email.message.Message) -> list:
    """获取附件信息"""
    attachments = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if filename:
            decoded_name = _decode_mime_header(filename)
            attachments.append({
                "filename": decoded_name,
                "content_type": part.get_content_type(),
                "size": len(part.get_payload(decode=True) or b"")
            })
    return attachments


def _connect_imap():
    """连接IMAP服务器"""
    if not _imap_host:
        return None, "IMAP服务器未配置"
    try:
        if _use_ssl:
            conn = imaplib.IMAP4_SSL(_imap_host, _imap_port)
        else:
            conn = imaplib.IMAP4(_imap_host, _imap_port)
        conn.login(_email_user, _email_pass)
        return conn, None
    except imaplib.IMAP4.error as e:
        return None, f"IMAP认证失败: {e}"
    except Exception as e:
        return None, f"IMAP连接失败: {e}"


@register
class ReadEmailTool(BaseTool):
    """读取邮件完整内容"""

    name: str = "read_email"
    description: str = "通过邮件ID读取指定邮件的完整内容，包括发件人、主题、正文、时间、附件等信息"
    parameters: Optional[dict] = {
        "type": "object",
        "properties": {
            "email_id": {
                "type": "integer",
                "description": "邮件序号（1为最新邮件），或传入邮件UID"
            },
            "use_uid": {
                "type": "boolean",
                "description": "是否使用UID模式，默认为False（使用序号）"
            }
        },
        "required": ["email_id"]
    }

    async def call(self, ctx, email_id: int, use_uid: bool = False) -> str:
        conn, err = _connect_imap()
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        try:
            conn.select("INBOX", readonly=True)
            if use_uid:
                typ, data = conn.uid("FETCH", str(email_id), "(RFC822)")
            else:
                typ, data = conn.fetch(str(email_id), "(RFC822)")

            if typ != "OK" or not data or not data[0]:
                return json.dumps({"success": False, "error": f"邮件 {email_id} 不存在"}, ensure_ascii=False)

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = _decode_mime_header(msg.get("Subject", ""))
            sender = _decode_mime_header(msg.get("From", ""))
            recipient = _decode_mime_header(msg.get("To", ""))
            date_str = msg.get("Date", "")
            try:
                date_dt = parsedate_to_datetime(date_str)
                date_formatted = date_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                date_formatted = date_str
            cc = _decode_mime_header(msg.get("Cc", ""))
            body = _get_email_body(msg)
            attachments = _get_attachments_info(msg)

            result = {
                "success": True,
                "data": {
                    "subject": subject,
                    "from": sender,
                    "to": recipient,
                    "date": date_formatted,
                    "cc": cc if cc else "",
                    "body": body,
                    "attachments": attachments
                }
            }
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass


@register
class SendEmailTool(BaseTool):
    """发送邮件"""

    name: str = "send_email"
    description: str = "发送电子邮件。需要提供收件人地址、邮件主题和正文内容"
    parameters: Optional[dict] = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "收件人邮箱地址，多个地址用英文逗号分隔"
            },
            "subject": {
                "type": "string",
                "description": "邮件主题"
            },
            "body": {
                "type": "string",
                "description": "邮件正文（纯文本）"
            }
        },
        "required": ["to", "subject", "body"]
    }

    async def call(self, ctx, to: str, subject: str, body: str) -> str:
        if not _smtp_host:
            return json.dumps({"success": False, "error": "SMTP服务器未配置"}, ensure_ascii=False)
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = _email_user
            msg["To"] = to

            if _use_ssl:
                with smtplib.SMTP_SSL(_smtp_host, _smtp_port) as server:
                    server.login(_email_user, _email_pass)
                    server.sendmail(_email_user, to.split(","), msg.as_string())
            else:
                with smtplib.SMTP(_smtp_host, _smtp_port) as server:
                    server.starttls()
                    server.login(_email_user, _email_pass)
                    server.sendmail(_email_user, to.split(","), msg.as_string())

            return json.dumps({"success": True, "message": f"邮件已发送至 {to}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@register
class CheckInboxTool(BaseTool):
    """查看收件箱"""

    name: str = "check_inbox"
    description: str = "查看收件箱中的最近邮件，返回发件人、主题和日期信息"
    parameters: Optional[dict] = {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "查看的邮件数量，默认10"
            }
        }
    }

    async def call(self, ctx, count: int = 10) -> str:
        conn, err = _connect_imap()
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        try:
            conn.select("INBOX", readonly=True)
            typ, data = conn.search(None, "ALL")
            if typ != "OK":
                return json.dumps({"success": False, "error": "无法搜索邮件"}, ensure_ascii=False)

            mail_ids = data[0].split()
            if not mail_ids:
                return json.dumps({"success": True, "data": [], "message": "收件箱为空"}, ensure_ascii=False)

            recent_ids = mail_ids[-count:]
            emails = []
            for mid in recent_ids:
                typ, msg_data = conn.fetch(mid, "(RFC822)")
                if typ != "OK":
                    continue
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                subject = _decode_mime_header(msg.get("Subject", ""))
                sender = _decode_mime_header(msg.get("From", ""))
                date_str = msg.get("Date", "")
                try:
                    date_dt = parsedate_to_datetime(date_str)
                    date_formatted = date_dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    date_formatted = date_str
                emails.append({
                    "id": int(mid),
                    "from": sender,
                    "subject": subject,
                    "date": date_formatted
                })

            emails.reverse()
            return json.dumps({"success": True, "data": emails}, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass


class EmailPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        global _imap_host, _imap_port, _smtp_host, _smtp_port
        global _email_user, _email_pass, _use_ssl
        _imap_host = cfg.get("imap_host", "")
        _imap_port = cfg.get("imap_port", 993)
        _smtp_host = cfg.get("smtp_host", "")
        _smtp_port = cfg.get("smtp_port", 465)
        _email_user = cfg.get("email_user", "")
        _email_pass = cfg.get("email_pass", "")
        _use_ssl = cfg.get("use_ssl", True)

    async def initialize(self):
        if _imap_host and _smtp_host:
            logger.info(f"邮件插件已初始化: IMAP={_imap_host}:{_imap_port}, SMTP={_smtp_host}:{_smtp_port}")
        else:
            logger.warning("邮件插件未配置完整，请设置 imap_host/smtp_host 等参数")

    async def terminate(self):
        pass