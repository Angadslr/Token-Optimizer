"""DeepSeek calls used by gui.py."""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI


ROUTE_LABELS = {
    "original": "1. Original prompt",
    "english": "2. English translation",
    "english_compressed": "3. Compressed English",
    "original_compressed": "4. Compressed original language",
}

TRANSFORMATION_PROMPTS = {
    "english": """
Translate the user's complete prompt faithfully into English.
Preserve all instructions, constraints, names, numbers, URLs, code, quotes,
and formatting requirements. Do not answer the prompt.
Return only the translated prompt.
""",
    "english_compressed": """
Translate the user's complete prompt into compact English.
Remove only filler, repeated politeness, redundancy, and duplicated instructions.
Preserve its meaning, tone, instructions, constraints, names, numbers, URLs,
code, quotes, and formatting requirements. Do not answer the prompt.
Return only the compact English prompt.
""",
    "original_compressed": """
Rewrite the user's complete prompt more compactly in its original language.
Remove only filler, repeated politeness, redundancy, and duplicated instructions.
Preserve its meaning, tone, instructions, constraints, names, numbers, URLs,
code, quotes, and formatting requirements. Do not translate or answer the prompt.
Return only the compact prompt.
""",
}


def load_api_key():
    """Read the NVIDIA API key from the environment or .env."""
    if "NVIDIA_API_KEY" not in os.environ and "DEEPSEEK_API_KEY" not in os.environ:
        env_file = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_file):
            with open(env_file, encoding="utf-8") as file:
                for line in file:
                    name = line.split("=", 1)[0].strip()
                    if name in ("NVIDIA_API_KEY", "DEEPSEEK_API_KEY"):
                        value = line.split("=", 1)[1].strip().strip("\"'")
                        os.environ[name] = value
                        break

    api_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY was not found in .env.")
    return api_key


def call_deepseek(messages):
    """Call DeepSeek V4 Flash through NVIDIA NIM and return its text."""
    client = OpenAI(
        api_key=load_api_key(),
        base_url="https://integrate.api.nvidia.com/v1",
        max_retries=5,
        timeout=120,
    )
    response = client.chat.completions.create(
        model="deepseek-ai/deepseek-v4-flash",
        messages=messages,
        temperature=0,
        max_tokens=2500,
        extra_body={"chat_template_kwargs": {"thinking": False}},
    )
    text = response.choices[0].message.content
    if not text or not text.strip():
        raise RuntimeError("DeepSeek returned an empty response.")
    return text.strip()


def transform_prompt(prompt, route):
    """Translate or compress a prompt for one route."""
    return call_deepseek(
        [
            {"role": "system", "content": TRANSFORMATION_PROMPTS[route]},
            {"role": "user", "content": prompt},
        ]
    )


def answer_prompt(prompt):
    """Ask DeepSeek to answer one routed prompt."""
    return call_deepseek([{"role": "user", "content": prompt}])


def run_four_routes(prompt, on_result=None):
    """Show the original, then transform and answer the other three routes."""
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    routed_prompts = {}
    results = {"original": (prompt, None)}

    # The original control is displayed exactly as entered and is not sent.
    if on_result:
        on_result("original", prompt, None)

    # First, create the three transformed prompts at the same time.
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = {
            executor.submit(transform_prompt, prompt, route): route
            for route in TRANSFORMATION_PROMPTS
        }
        for job in as_completed(jobs):
            route = jobs[job]
            try:
                routed_prompts[route] = job.result()
            except Exception as error:
                message = f"Transformation failed: {error}"
                results[route] = (None, message)
                if on_result:
                    on_result(route, None, message)

    # Then, ask DeepSeek to answer each prompt at the same time.
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = {
            executor.submit(answer_prompt, text): route
            for route, text in routed_prompts.items()
        }
        for job in as_completed(jobs):
            route = jobs[job]
            try:
                answer, error = job.result(), None
            except Exception as exception:
                answer, error = None, f"Answer call failed: {exception}"

            results[route] = (answer, error)
            if on_result:
                on_result(route, answer, error)

    return results
