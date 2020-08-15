import re
import emoji


def remove_emojis(text):
    replaced_text = None
    if text:
        replaced_text = re.sub(emoji.get_emoji_regexp(), r"", text).strip()
    return replaced_text
