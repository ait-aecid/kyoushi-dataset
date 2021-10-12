"""The main entry point for the Cyber Range Kyoushi Dataset CLI"""

if __name__ == "__main__":
    import sys

    from .cli import cli

    cli(prog_name=f"{sys.executable} -m {__package__}")
