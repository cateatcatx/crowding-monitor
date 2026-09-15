Forward P/E regression fixtures: source PNGs retrieved from Yardeni on 2026-09-08,
both showing the 2026-09-04 legend (semiconductors 16.7, application software 23.4).
Copyright/source attribution is preserved in each image. These are frozen test
fixtures, not the live dashboard cache. The OCR JSON records were visually checked
against the axis labels and legends; tests use them without network or model inference.

The additional application-software fixture dated 2026-09-14 (22.0x) was retrieved
on 2026-09-15. It reproduces the endpoint-median false rejection: the final pixel
column spans multiple days, so its visible PE envelope, not its median, must be
compared with the legend. This is unrelated to interpolating missing observations.

- https://yardeni.com/charts/domestic-industry-briefings/s-p-500-information-technology/semiconductors
- https://yardeni.com/charts/domestic-industry-briefings/s-p-500-information-technology/application-software
