JOERN_PATH = ""
CTAGS_PATH = ""
NOTION_TOKEN = ""
DATABASE_ID = ""
GPT_API_KEY = ""
SIM_THRESHOLD = 0.55
SLICE_LEVEL = 1
PLACE_HOLDER = "    /* PLACEHOLDER: DO NOT DELETE THIS COMMENT */"
PORT = 5000
PROMPT_TEMPLATE = {
    "instruction": (
        """I will give you 2 inputs:
1. a patch
2. a vulnerable function
Your task is to refer to the patch to fix the vulnerable function, and output the fixed function.

Here are the requirements for your output:
1. The patch I gave you may not be directly applicable to the vulnerable function, and you will need to make adaptation adjustments.
2. You only need to adapt and fix the patch part, do not make any other fixes or improvements.
3. Maintain the original style of the code as much as possible.
4. Do not delete or add any comments in the code.
5. You may notice that there are some missing parts in the code I gave you, but it's okay, don't fill in the missing parts. You just need to output the fixed code."""
    ),
    "context": (
        "### Original Function Patch:\n{patch_original}\n\n"
        "### Vulnerable Function:\n{func_before_target}\n\n"
    ),
    "output": "### Fixed Function:\n{func_after_target}\n\n"
}
PROMPT_TEMPLATE_DICT = {
    "trans_patch": PROMPT_TEMPLATE,
}
