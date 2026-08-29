from agents.tools.calculator import addition

from agents.tools.file_tools import (
    write_file,
    read_file,
    run_python
)

from agents.tools.web import (
    fetch_webpage
)


TOOLS = {

    "addition":
        addition,

    "write_file":
        write_file,

    "read_file":
        read_file,

    "run_python":
        run_python,

    "fetch_webpage":
        fetch_webpage

}