import matplotlib.pyplot as plt
import numpy as np
import random
import json
random.seed(42)
plt.rcParams['font.family'] = 'Times New Roman'
def generate_data():
    with open("token_threshold.json", "r") as fr:
        vul_threshols = json.load(fr)
    CVE_Succ_Rate = np.array([vul_threshols["1,024"]["CVE Succ Rate"], vul_threshols["2,048"]["CVE Succ Rate"],vul_threshols["4,096"]["CVE Succ Rate"],vul_threshols["8,192"]["CVE Succ Rate"],vul_threshols["16,384"]["CVE Succ Rate"]])
    Func_Succ_Rate = np.array([vul_threshols["1,024"]["Func Succ Rate"], vul_threshols["2,048"]["Func Succ Rate"],vul_threshols["4,096"]["Func Succ Rate"],vul_threshols["8,192"]["Func Succ Rate"],vul_threshols["16,384"]["Func Succ Rate"]])
    return CVE_Succ_Rate, Func_Succ_Rate
thresholds = np.array([1024, 2048, 4096, 8192, 16384])
fig, ax = plt.subplots(figsize=(5, 5))
CVE_Succ_Rate, Func_Succ_Rate = generate_data()
max_f1_index = np.argmax(CVE_Succ_Rate)
max_f1 = CVE_Succ_Rate[max_f1_index]
max_f1_threshold = thresholds[max_f1_index]
ax.plot(thresholds, CVE_Succ_Rate, label='CVE Succ Rate', marker='s', linewidth=2, color='#b7e5ff')
ax.plot(thresholds, Func_Succ_Rate, label='Func Succ Rate', marker='^', linewidth=2, color='#F46F43')
ax.set_xlabel('Threshold')
ax.legend(loc='lower left')
ax.grid(True)
ax.set_xticks(thresholds)
ax.set_xticklabels(['1k', '2k', '4k', '8k', '16k'], fontsize=10)
ax.set_ylim(0.5, 1)
plt.tight_layout()
pdf_path = 'token.pdf'
plt.savefig(pdf_path)
plt.show()