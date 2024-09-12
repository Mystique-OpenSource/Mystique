import os

import cpu_heater
import difftools
import format
import joern
from common import Language


def export_joern_graph(pre_dir: str, post_dir: str, target_dir: str, need_cdg: bool, language: Language, multiprocess: bool = False, overwrite: bool = False):
    worker_args = [
        (f"{pre_dir}/code", pre_dir, language, need_cdg, overwrite),
        (f"{post_dir}/code", post_dir, language, need_cdg, overwrite),
        (f"{target_dir}/code", target_dir, language, need_cdg, overwrite)
    ]
    if multiprocess:
        cpu_heater.multiprocess(worker_args, joern.export_with_preprocess_and_merge, max_workers=3, show_progress=False)
    else:
        joern.export_with_preprocess_and_merge(*worker_args[0])
        joern.export_with_preprocess_and_merge(*worker_args[1])
        joern.export_with_preprocess_and_merge(*worker_args[2])


def export_joern_graph_pre_post(pre_dir: str, post_dir: str, need_cdg: bool, language: Language, multiprocess: bool = False, overwrite: bool = False):
    worker_args = [
        (f"{pre_dir}/analysis", pre_dir, language, need_cdg, overwrite),
        (f"{post_dir}/analysis", post_dir, language, need_cdg, overwrite)
    ]
    if multiprocess:
        cpu_heater.multiprocess(worker_args, joern.export_with_preprocess_and_merge, max_workers=3, show_progress=False)
    else:
        joern.export_with_preprocess_and_merge(*worker_args[0])
        joern.export_with_preprocess_and_merge(*worker_args[1])


def write2file(file_path: str, content: str):
    with open(file_path, "w") as f:
        f.write(content)


def write2method(method_dir: str, file_name: str, content: str):
    write2file(os.path.join(method_dir, file_name), content)


def method_diff2html(method_dir: str, suffix: str):
    pre = os.path.join(method_dir, f"1.pre{suffix}")
    post = os.path.join(method_dir, f"2.post{suffix}")
    target = os.path.join(method_dir, f"3.target{suffix}")
    gt = os.path.join(method_dir, f"4.gt{suffix}")

    pre_s = os.path.join(method_dir, f"1.pre@s{suffix}")
    post_s = os.path.join(method_dir, f"2.post@s{suffix}")
    target_s = os.path.join(method_dir, f"3.target@s{suffix}")
    gt_s = os.path.join(method_dir, f"4.gt@s{suffix}")

    pre_sp = os.path.join(method_dir, f"1.pre@sp{suffix}")
    post_sp = os.path.join(method_dir, f"2.post@sp{suffix}")
    target_sp = os.path.join(method_dir, f"3.target@sp{suffix}")
    gt_sp = os.path.join(method_dir, f"4.gt@sp{suffix}")

    ours = os.path.join(method_dir, f"5.ours{suffix}")
    ours_s = os.path.join(method_dir, f"5.ours@s{suffix}")
    ours_sp = os.path.join(method_dir, f"5.ours@sp{suffix}")
    ours_ans = os.path.join(method_dir, f"5.ours@ans{suffix}")
    ours_tns = os.path.join(method_dir, f"5.ours@tns{suffix}")
    ours_ag = os.path.join(method_dir, f"5.ours@ag{suffix}")

    diff_dir = os.path.join(method_dir, "diff")

    pre_post = os.path.join(diff_dir, "pre-post.html")
    pre_target = os.path.join(diff_dir, "pre-target.html")
    target_gt = os.path.join(diff_dir, "target-gt.html")

    pre_pre_s = os.path.join(diff_dir, "pre-pre@s.html")
    post_post_s = os.path.join(diff_dir, "post-post@s.html")
    target_target_s = os.path.join(diff_dir, "target-target@s.html")
    gt_gt_s = os.path.join(diff_dir, "gt-gt@s.html")

    pre_post_s = os.path.join(diff_dir, "pre@s-post@s.html")
    pre_target_s = os.path.join(diff_dir, "pre@s-target@s.html")
    target_gt_s = os.path.join(diff_dir, "target@s-gt@s.html")

    pre_post_sp = os.path.join(diff_dir, "pre@sp-post@sp.html")
    pre_target_sp = os.path.join(diff_dir, "pre@sp-target@sp.html")
    target_gt_sp = os.path.join(diff_dir, "target@sp-gt@sp.html")

    target_ours = os.path.join(diff_dir, "target-ours.html")
    target_ours_s = os.path.join(diff_dir, "target@s-ours@s.html")
    target_ours_sp = os.path.join(diff_dir, "target@sp-ours@sp.html")

    ours_gt = os.path.join(diff_dir, "ours-gt.html")
    ours_gt_s = os.path.join(diff_dir, "ours@s-gt@s.html")
    ours_gt_sp = os.path.join(diff_dir, "ours@sp-gt@sp.html")

    ours_gt_ans = os.path.join(diff_dir, "ours@ans-gt.html")
    ours_gt_tns = os.path.join(diff_dir, "ours@tns-gt.html")
    ours_gt_ag = os.path.join(diff_dir, "ours@ag-gt.html")

    difftools.diff2html_file(pre, post, pre_post)
    difftools.diff2html_file(pre, target, pre_target)
    difftools.diff2html_file(target, gt, target_gt)

    difftools.diff2html_file(pre, pre_s, pre_pre_s)
    difftools.diff2html_file(post, post_s, post_post_s)
    difftools.diff2html_file(target, target_s, target_target_s)
    difftools.diff2html_file(gt, gt_s, gt_gt_s)

    difftools.diff2html_file(pre_s, post_s, pre_post_s)
    difftools.diff2html_file(pre_s, target_s, pre_target_s)
    difftools.diff2html_file(target_s, gt_s, target_gt_s)

    difftools.diff2html_file(pre_sp, post_sp, pre_post_sp)
    difftools.diff2html_file(pre_sp, target_sp, pre_target_sp)
    difftools.diff2html_file(target_sp, gt_sp, target_gt_sp)

    difftools.diff2html_file(target, ours, target_ours)
    difftools.diff2html_file(target_s, ours_s, target_ours_s)
    difftools.diff2html_file(target_sp, ours_sp, target_ours_sp)

    difftools.diff2html_file(ours, gt, ours_gt)
    difftools.diff2html_file(ours_s, gt_s, ours_gt_s)
    difftools.diff2html_file(ours_sp, gt_sp, ours_gt_sp)

    difftools.diff2html_file(ours_ans, gt, ours_gt_ans)
    difftools.diff2html_file(ours_tns, gt, ours_gt_tns)
    difftools.diff2html_file(ours_ag, gt, ours_gt_ag)


def group_consecutive_ints(nums: list[int]) -> list[list[int]]:
    if len(nums) == 0:
        return []
    nums.sort()
    result = [[nums[0]]]
    for num in nums[1:]:
        if num == result[-1][-1] + 1:
            result[-1].append(num)
        else:
            result.append([num])
    return result


def recursive_parent_find(path: str, filename: str, all_files: list[str]) -> str | None:
    while True:
        if os.path.join(path, filename) in all_files:
            return path
        if path == "" or path == "/":
            return None
        path = os.path.dirname(path)


def line2offset(text: str, line: int) -> int:
    return len("\n".join(text.split("\n")[:line - 1]))


def exact_match(a: str, b: str) -> bool:
    if a == b:
        return True
    a = format.normalize(a, del_comments=False)
    b = format.normalize(b, del_comments=False)
    return a == b
