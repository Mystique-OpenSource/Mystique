import matplotlib.pyplot as plt
import numpy as np
import random
import json
random.seed(42)
plt.rcParams['font.family'] = 'Times New Roman'
def generate_data():
    with open("slice_threshold.json", "r") as fr:
        vul_threshols = json.load(fr)
    CVE_Succ_Rate = np.array([vul_threshols["1"]["CVE Succ Rate"], vul_threshols["2"]["CVE Succ Rate"],vul_threshols["3"]["CVE Succ Rate"],vul_threshols["4"]["CVE Succ Rate"],vul_threshols["5"]["CVE Succ Rate"]])
    Func_Succ_Rate = np.array([vul_threshols["1"]["Func Succ Rate"], vul_threshols["2"]["Func Succ Rate"],vul_threshols["3"]["Func Succ Rate"],vul_threshols["4"]["Func Succ Rate"],vul_threshols["5"]["Func Succ Rate"]])
    return CVE_Succ_Rate, Func_Succ_Rate
thresholds = np.arange(1, 6, 1)
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
ax.set_xticks(np.arange(1, 6, 1))
ax.set_ylim(0.5, 1) 
plt.tight_layout()
pdf_path = 'slice.pdf'
plt.savefig(pdf_path)
plt.show()
