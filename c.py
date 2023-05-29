import json
import matplotlib.pyplot as plt

data = """
{
  "max_worker": [
    1,
    2,
    4,
    8,
    16,
    32
  ],
  "chunk_size": [
    10000000,
    25000000,
    50000000,
    100000000
  ],
  "download_time": [
    [
      11.26774368700012,
      5.7431641210000635,
      3.2192887039996094,
      2.5244074879997243,
      2.7652586089998294,
      2.8691875210001854
    ],
    [
      10.750790609999967,
      5.619217531000231,
      2.999810545999935,
      2.3160191690003558,
      2.6309392419998403,
      2.5510593799999697
    ],
    [
      10.55899003400009,
      5.586918591000085,
      2.974375512000279,
      2.3696315299998787,
      2.9254619449998245,
      2.7947660429999814
    ],
    [
      10.498739763999765,
      5.544950600999982,
      3.4807175229998393,
      2.5388284450000356,
      2.2156880640000054,
      2.2499813370000084
    ]
  ]
}
"""
data = json.loads(data)
for (
    dt,
    cs,
) in zip(data["download_time"], data["chunk_size"]):
    plt.plot(data["max_worker"], dt, "-o", label=str(cs // 1000_000) + " MB")
plt.xlabel("max_workers")
plt.xticks(data["max_worker"])
plt.ylabel("download_time [sec]")
plt.grid(color="gray", linestyle="--", linewidth=0.5)
plt.legend(bbox_to_anchor=(1.05, 1.0), loc="upper left")
plt.tight_layout()
plt.show()
