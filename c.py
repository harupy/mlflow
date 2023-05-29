import json
import matplotlib.pyplot as plt
import numpy as np

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
      0.45653269099784666,
      0.4737581109984603,
      0.4550955890008481,
      0.45823802599988994,
      0.45580331800010754,
      0.4547827639980824
    ],
    [
      0.45493109800008824,
      0.4543599790013104,
      0.45697306700094487,
      0.4550259030002053,
      1.098904655998922,
      2.0334309870013385
    ],
    [
      2.851687178997963,
      3.6770369879995997,
      4.166486403999443,
      4.400169076001475,
      4.471886161998555,
      4.516391736000514
    ],
    [
      4.5417703530001745,
      4.5171642060013255,
      4.5184957519995805,
      4.504199107999739,
      4.49116821500138,
      4.507314325997868
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
plt.legend(bbox_to_anchor=(1.05, 1.0), loc="upper left")
plt.tight_layout()
plt.show()
