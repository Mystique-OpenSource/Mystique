import matplotlib.pyplot as plt
import numpy as np
import random
import json
random.seed(42)
plt.rcParams['font.family'] = 'Times New Roman'
def generate_data():
    with open("ov_threshold.json", "r") as fr:
        vul_threshols = json.load(fr)
    CVE_Succ_Rate = np.array([vul_threshols["0.1"]["CVE Succ Rate"], vul_threshols["0.2"]["CVE Succ Rate"],vul_threshols["0.3"]["CVE Succ Rate"],vul_threshols["0.4"]["CVE Succ Rate"],vul_threshols["0.5"]["CVE Succ Rate"],vul_threshols["0.6"]["CVE Succ Rate"],vul_threshols["0.7"]["CVE Succ Rate"],vul_threshols["0.8"]["CVE Succ Rate"],vul_threshols["0.9"]["CVE Succ Rate"]])
    Func_Succ_Rate = np.array([vul_threshols["0.1"]["Func Succ Rate"], vul_threshols["0.2"]["Func Succ Rate"],vul_threshols["0.3"]["Func Succ Rate"],vul_threshols["0.4"]["Func Succ Rate"],vul_threshols["0.5"]["Func Succ Rate"],vul_threshols["0.6"]["Func Succ Rate"],vul_threshols["0.7"]["Func Succ Rate"],vul_threshols["0.8"]["Func Succ Rate"],vul_threshols["0.9"]["Func Succ Rate"]])
    return CVE_Succ_Rate, Func_Succ_Rate
thresholds = np.arange(0.1, 1.0, 0.1)
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
ax.set_xticks(np.arange(0.1, 1.0, 0.1))
ax.set_ylim(0.5, 1)
plt.tight_layout()
pdf_path = 'ov.pdf'
plt.savefig(pdf_path)
plt.show()
