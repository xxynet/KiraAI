from pathlib import Path
from core.llm_client import LLMClient
from core.tool_manager import register_all_tools


llm_api = LLMClient()

# llm_api.register_tool(
#     name="add_numbers",
#     description="将两个数字相加",
#     parameters={
#         "type": "object",
#         "properties": {
#             "a": {"type": "number"},
#             "b": {"type": "number"}
#         },
#         "required": ["a", "b"]
#     },
#     func=lambda a, b: {"result": a + b}
# )
#
#
# def exec_code(code: str):
#     try:
#         old_stdout = sys.stdout
#         redirected_output = sys.stdout = StringIO()
#
#         exec(code)
#
#         sys.stdout = old_stdout
#
#         output = redirected_output.getvalue()
#         return f"执行成功，输出：{output}"
#     except Exception as e:
#         return f"执行失败 {str(e)}"
#
#
# llm_api.register_tool(
#     name="python",
#     description="执行Python代码，可以通过此工具操作电脑",
#     parameters={
#         "type": "object",
#         "properties": {
#             "code": {"type": "string", "description": "要执行的代码"}
#         },
#         "required": ["code"]
#     },
#     func=exec_code
# )


register_all_tools(llm_api)

if __name__ == '__main__':
    pass
