import sys

try:
    import IPython.display as ipython_display
except ModuleNotFoundError:
    ipython_display = None  # type: ignore  # pylint: disable=C0103


def is_interactive():
    # pylint: disable=C0415
    import __main__ as main
    return not hasattr(main, "__file__")


def print_error_msg(msg: str):
    print(msg, file=sys.stderr)


def clear_notebook_cell_output(wait: bool = False):
    if not ipython_display:
        return
    ipython_display.clear_output(wait=wait)

