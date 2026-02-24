import psutil
import datetime
import platform

from core.utils.tool_utils import BaseTool


def get_size(bytes):
    '''转换数据单位'''
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024.0:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.2f} PB"


def get_system_info():
    # CPU
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_cores = psutil.cpu_count(logical=True)

    # 内存
    memory = psutil.virtual_memory()
    memory_total = get_size(memory.total)
    memory_percent = memory.percent

    # 磁盘
    disk = psutil.disk_usage('/')
    disk_total = get_size(disk.total)
    disk_percent = disk.percent

    # 网络
    net_io = psutil.net_io_counters()
    net_sent = get_size(net_io.bytes_sent)
    net_recv = get_size(net_io.bytes_recv)

    # 系统启动时间
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    boot_time_str = boot_time.strftime("%Y-%m-%d %H:%M:%S")

    # 进程数
    process_count = len(psutil.pids())

    # 网络连接数
    connections_count = len(psutil.net_connections())

    # 操作系统
    system = f"{platform.system()} {platform.release()}"

    # 构建输出
    output = []
    output.append(f"CPU 使用率: {cpu_percent:.1f}%")
    output.append(f"CPU 核心数: {cpu_cores}")
    output.append(f"内存总量: {memory_total}")
    output.append(f"内存使用: {memory_percent:.1f}%")
    output.append(f"磁盘总量: {disk_total}")
    output.append(f"磁盘使用: {disk_percent:.1f}%")
    output.append(f"网络发送: {net_sent}")
    output.append(f"网络接收: {net_recv}")
    output.append(f"系统启动时间: {boot_time_str}")
    output.append(f"当前运行进程数: {process_count}")
    output.append(f"当前网络连接数: {connections_count}")
    output.append(f"系统: {system}")

    return "\n".join(output)


class GetSystemInfoTool(BaseTool):
    name = "get_sysinfo"
    description = "获取你当前运行所在设备的配置以及占用情况"
    parameters = {
        "type": "object",
        "properties": {
        },
        "required": []
    }

    async def execute(self) -> str:
        try:
            return get_system_info()
        except Exception as e:
            return f"获取系统信息时出错：{str(e)}"