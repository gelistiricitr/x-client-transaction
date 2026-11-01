import re

ADDITIONAL_RANDOM_NUMBER: int = 3
DEFAULT_KEYWORD: str = "obfiowerehiring"

ON_DEMAND_FILE_URL: str = "https://abs.twimg.com/responsive-web/client-web/ondemand.s.{filename}a.js"
ON_DEMAND_FILE_REGEX: re.Pattern = re.compile(
    r"""[,{](\d+):["']ondemand\.s["']""", flags=(re.VERBOSE | re.MULTILINE))
ON_DEMAND_HASH_PATTERN: str = r'[,{{]{}:["\']([0-9a-f]+)["\']'
ONDEMAND_HASH_PATTERN: str = ON_DEMAND_HASH_PATTERN

XWEB_ENTRY_REGEX: re.Pattern = re.compile(
    r"""https://abs\.twimg\.com/x-web/[^\s"'`<>]+/entry-client-[^\s"'`<>]+\.js""")
XWEB_SIGN_REGEX: re.Pattern = re.compile(
    r"""["'`]([^"'`\s<>]*sign\.o-[^"'`\s<>]+\.js)["'`]""")
XWEB_STARTUP_REGEX: re.Pattern = re.compile(
    r"""["'`]([^"'`\s<>]*startup(?:-dynamic)?-[^"'`\s<>]+\.js)["'`]""")

INDICES_REGEX: re.Pattern = re.compile(
    r"""(\([a-zA-Z_$][\w$]{0,2}\[(\d{1,2})\],\s*16\))+""", flags=(re.VERBOSE | re.MULTILINE))

MIGRATION_REDIRECTION_REGEX: re.Pattern = re.compile(
    r"""(http(?:s)?://(?:www\.)?(twitter|x){1}\.com(/x)?/migrate([/?])?tok=[a-zA-Z0-9%\-_]+)+""", re.VERBOSE)


if __name__ == "__main__":
    pass
