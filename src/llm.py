import base64
import json
import logging

import requests
import sseclient
from openai import OpenAI

import config
from ast_parser import ASTParser
from common import Language
from config import PORT, PROMPT_TEMPLATE

client = OpenAI(api_key=base64.b64decode(config.GPT_API_KEY).decode("utf-8"))


def clean_llm_output(output: str, language: Language) -> str:
    output = output.replace("```java", "").replace("```c", "").replace("```", "")
    ast_parser = ASTParser(output, language)
    func_node = None
    if language == Language.JAVA:
        func_node = ast_parser.query_oneshot("(method_declaration)@func")
    elif language == Language.C:
        func_node = ast_parser.query_oneshot("(function_definition)@func")
    if func_node is not None:
        assert func_node.text is not None
        output = func_node.text.decode()
    return output


def llm_fix(patch: str, vulcode: str, language: Language) -> None | str:
    llm_output = gpt_fix(patch, vulcode, language)
    logging.debug(f"LLM output: \n{llm_output}")
    if llm_output is None:
        return
    fixed_code = clean_llm_output(llm_output, language)
    return fixed_code


def codellama_fix(patch: str, vulcode: str) -> None | str:
    example = {
        "patch_original": patch,
        "func_before_target": vulcode}
    prompt = PROMPT_TEMPLATE["instruction"].format_map(example) + PROMPT_TEMPLATE["context"].format_map(example)
    url = f"http://127.0.0.1:{PORT}/v1/completions"
    headers = {
        "Content-Type": "application/json"
    }

    data = {
        "mode": "instruct",
        "prompt": prompt,
        "max_tokens": 4096,
        "temperature": 0,
        "top_p": 0.5,
        "seed": 10,
        "stream": True
    }

    stream_response = requests.post(url, headers=headers, json=data, verify=False, stream=True)
    client = sseclient.SSEClient(stream_response)  # type: ignore
    full_text = ""
    for event in client.events():
        payload = json.loads(event.data)
        full_text += payload['choices'][0]['text']
    return full_text


def llm_merge(patch: str, vulcode: str, language: Language) -> None | str:
    llm_output = gpt_merge(patch, vulcode, language)
    logging.debug(f"LLM output: \n{llm_output}")
    if llm_output is None:
        return
    fixed_code = clean_llm_output(llm_output, language)
    return fixed_code


def gpt_fix(patch: str, vulcode: str, language: Language) -> str | None:
    code_language = "Java" if language == Language.JAVA else "C"
    content = f"""
Patch:
{patch}

Code to be fixed:
{vulcode}
"""
    logging.debug(f"🤖 GPT Input: {content}")
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            temperature=0.5,
            messages=[
                {
                    "role": "system",
                    "content": f"You're a professional and cautious {code_language} programmer, and you're very good at patching programs. Now I'm going to give you a patch and a piece of code to fix, but it's worth noting that the patch you've been given won't necessarily work directly with this code; you'll need to adapt it. You only need to adapt and fix the patch part, do not make any other fixes or improvements. Maintain the original style of the code as much as possible. Do not delete or add any comments in the code. You may notice that there are some missing parts in the code I gave you, but it's okay, don't fill in the missing parts. You just need to output the fixed code!",
                },
                {
                    "role": "user",
                    "content": content,
                },
            ],
        )
        result = completion.choices[0].message.content
    except Exception as e:
        return
    return result


def gpt_merge(patch: str, vulcode: str, language: Language) -> str | None:
    content = f"""
Patch:
{patch}

Code to be fixed:
{vulcode}
"""
    logging.debug(f"🤖 GPT Input: {content}")
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": "You're a professional Java programmer. Now I'm going to give you a patch and a piece of code to merge. You only need to merge the patch part, do not make any other fixes or improvements. Maintain the original style of the code as much as possible. Do not delete or add any comments in the code. You may notice that there are some missing parts in the code I gave you, but it's okay, don't fill in the missing parts. You just need to output the merged code!",
                },
                {
                    "role": "user",
                    "content": content,
                },
            ],
        )
        result = completion.choices[0].message.content
    except Exception as e:
        logging.error(f"❌ GPT Failed: {e}")
        return
    return result


def gpt_ppathf(pre_method: str, post_method: str, target_method: str) -> str | None:
    content = f"""
Below is a patch (including function before and function after) from R1, paired with a corresponding function before from R2. Adapt the patch from R1 to R2 by generating the function after based on the given function before.


Function Before R1:
{pre_method}


Function After R1:
{post_method}

Function Before R2:
{target_method}

Function After R2:

"""
    logging.debug(f"🤖 GPT Input: {content}")
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": content,
                },
            ],
        )
        result = completion.choices[0].message.content
    except Exception as e:
        logging.error(f"❌ GPT Failed: {e}")
        return
    return result
