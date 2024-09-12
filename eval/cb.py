import sys

import codebleu
import cpu_heater

sys.path.append('../2.Method/patchbp')
from common import Language


def calc_codebleu(prediction: str, reference: str, language: Language):
    lang = "c" if language == Language.C else "java"
    result = codebleu.calc_codebleu([reference], [prediction], lang=lang,
                                    weights=(0.10, 0.10, 0.40, 0.40), tokenizer=None)
    return result["codebleu"]


def codebleu_batch(pred_refs: list[tuple[str, str]], language: Language) -> float:
    lang = "c" if language == Language.C else "java"
    args = [(ref, pred, lang) for pred, ref in pred_refs]
    score_list = cpu_heater.multiprocess(calc_codebleu, args, show_progress=True)
    score = sum(score_list) / len(score_list)
    return score


if __name__ == "__main__":
    prediction = "a = b;\n c = a;\n z = c;/* hi */"
    reference = "a = b;\n c = a;\n z = c;"
    print(calc_codebleu(prediction, reference, Language.C))
    print(codebleu_batch([(prediction, reference)], Language.C))
