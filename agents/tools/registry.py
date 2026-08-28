from agents.tools.calculator import addition
from agents.tools.file_tools import write_file, read_file, run_python


TOOLS = {
    "addition": addition,
    "write_file": write_file,
    "read_file": read_file,
    "run_python": run_python
}