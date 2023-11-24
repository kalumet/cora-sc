class Printr:
    LILA = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CLEAR = "\033[0m"
    BOLD = "\033[1m"
    FAINT = "\033[2m"
    NORMAL_WEIGHT = "\033[22m"
    UNDERLINE = "\033[4m"
    END_UNDERLINE = "\033[24m"
    OVERLINE = "\033[53m"
    END_OVERLINE = "\033[55m"
    FRAMED = "\033[51m"
    ENCIRCLED = "\033[52m"
    DELETE_LINE = "\033[2K\033[1G"
    PREVIOUS_LINE = "\033[2F"

    @staticmethod
    def clr(text, color_format):
        return f"{color_format}{text}{Printr.CLEAR}"

    @staticmethod
    def clr_print(text, color_format):
        print(Printr.clr(text, color_format))

    @staticmethod
    def sys_print(text, headline="", color=RED, first_message=True):
        if first_message:
            print("")
            if headline.strip():
                print(
                    Printr.clr(f"{Printr.BOLD}{headline}{Printr.NORMAL_WEIGHT}", color)
                )
        else:
            print(Printr.PREVIOUS_LINE)
        print(Printr.clr(f"⎢ {text}", color))
        print("")

    @staticmethod
    def err_print(text, first_message=True):
        Printr.sys_print(text, "Something went wrong!", first_message=first_message)

    @staticmethod
    def warn_print(text, first_message=True):
        Printr.sys_print(text, "Please note:", Printr.YELLOW, first_message)

    @staticmethod
    def info_print(text, first_message=True):
        Printr.sys_print(text, "", Printr.BLUE, first_message)

    @staticmethod
    def hl_print(text, first_message=True):
        Printr.sys_print(text, "", Printr.CYAN, first_message)

    @staticmethod
    def override_print(text):
        print(f"{Printr.DELETE_LINE}{text}")

    @staticmethod
    def box_start():
        print(
            f"{Printr.CYAN}⎡{Printr.OVERLINE}⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊{Printr.END_OVERLINE}⎤"
        )
        print(f"⎢{Printr.CLEAR}")

    @staticmethod
    def box_end():
        print(f"{Printr.CYAN}⎢")
        print(
            f"⎣{Printr.UNDERLINE}⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊{Printr.END_UNDERLINE}⎦{Printr.CLEAR}"
        )

    @staticmethod
    def box_print(text):
        print(f"{Printr.CYAN}⎜{Printr.CLEAR}  {text}")
