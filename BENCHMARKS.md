# seamgraph Benchmark Results

Tested against 20 real-world OSS repositories.

## Methodology

- Each repo is cloned with `--depth=300 --single-branch --filter=blob:none`:
  the working tree plus 300 commits of history (no historical blobs), which
  is all the co-change miner needs.
- *Anchors* are pattern-anchored reference endpoints; *seams* are matched
  edges; *corroborated* seams additionally have co-change support >= 3 with
  directional confidence >= 0.25 in the 300-commit window; *discoveries* are
  cross-artifact file pairs with high co-change but no static seam.
- Numbers are produced by `python tests/benchmark_real_repos.py --keep` and
  are fully deterministic for a given set of clone heads.
- Warning-severity orphans (not shown per-repo below) averaged ~12 per repo
  across the corpus; every sampled warning was hand-verified as either a
  genuine dead reference (e.g. papermark's frontend calling
  `/api/teams/{id}/billing/manage` with no such handler) or an extraction
  gap that was then fixed and re-run before these numbers were published.

## Summary Table

| Repo | Description | Files | Anchors | Seams | Corroborated | Discoveries | Time (s) |
|------|-------------|------:|--------:|------:|-------------:|------------:|---------:|
| fastapi-full-stack | FastAPI+React official template | 236 | 198 | 104 | 0 | 0 | 0.41 |
| saleor | Django e-commerce platform | 4,611 | 1,650 | 919 | 4 | 0 | 11.74 |
| saleor-dashboard | React dashboard for Saleor | 5,467 | 339 | 206 | 6 | 0 | 5.82 |
| label-studio | Django+React data labeling | 5,183 | 2,148 | 1,103 | 0 | 0 | 5.84 |
| redash | Flask+React dashboards | 1,288 | 613 | 194 | 0 | 1 | 1.61 |
| plane | Django+Next.js project management | 5,405 | 2,490 | 896 | 0 | 6 | 6.08 |
| cal.com | Next.js scheduling platform | 7,674 | 2,225 | 4,085 | 0 | 0 | 7.59 |
| immich | TS+Svelte photo management | 3,846 | 602 | 48 | 0 | 0 | 3.49 |
| listmonk | Go+Vue newsletter manager | 506 | 185 | 3 | 0 | 0 | 0.5 |
| maybe | Ruby+React finance app | 1,601 | 90 | 1 | 0 | 0 | 0.58 |
| documenso | Next.js document signing | 2,794 | 866 | 998 | 0 | 0 | 3.23 |
| rallly | Next.js scheduling polls | 1,436 | 371 | 146 | 3 | 0 | 1.1 |
| formbricks | Next.js survey platform | 4,105 | 1,020 | 308 | 57 | 0 | 5.64 |
| papermark | Next.js document sharing | 1,703 | 1,064 | 600 | 35 | 0 | 2.79 |
| dify | Flask+React LLM app platform | 13,480 | 3,760 | 1,503 | 0 | 0 | 27.32 |
| open-webui | Svelte+Python chat UI | 4,951 | 1,919 | 100 | 26 | 3 | 4.36 |
| lobe-chat | Next.js chat application | 12,970 | 2,776 | 2,689 | 111 | 2 | 19.26 |
| twenty | TS+React CRM | 25,930 | 1,385 | 1,897 | 0 | 0 | 22.42 |
| infisical | Next.js secret management | 12,972 | 1,697 | 328 | 0 | 0 | 13.85 |
| hoppscotch | Vue.js API development | 2,362 | 426 | 79 | 0 | 0 | 3.26 |
| **Total** | | **118,520** | **25,824** | **16,207** | **242** | **12** | |

## Seams by Kind (aggregated)

| Kind | Count |
|------|------:|
| env | 11,722 |
| route | 2,385 |
| setting | 1,560 |
| script | 242 |
| urlname | 217 |
| template | 81 |

## Anchors by Kind (aggregated)

| Kind | Count |
|------|------:|
| env_read | 7,398 |
| env_def | 6,458 |
| route_call | 3,039 |
| route_def | 2,305 |
| setting_read | 2,047 |
| script_def | 1,973 |
| urlname_def | 632 |
| script_use | 600 |
| setting_def | 553 |
| task_def | 290 |
| template_file | 257 |
| urlname_ref | 190 |
| template_ref | 82 |

## Orphans by Problem (aggregated)

| Problem | Count |
|---------|------:|
| env-use-unmatched | 4,523 |
| env-def-unused | 3,553 |
| route-def-uncalled | 1,913 |
| script-def-unused | 1,810 |
| route-call-unmatched | 1,702 |
| setting-use-unmatched | 651 |
| urlname-def-unused | 589 |
| task-def-uncalled | 290 |
| setting-def-unused | 221 |
| template-file-unreferenced | 115 |
| script-use-unmatched | 17 |
| urlname-use-unmatched | 12 |
| route-call-unspecific | 4 |
| template-ref-missing | 1 |

## Per-Repo Details

### fastapi-full-stack
*FastAPI+React official template*

**Anchors:** env_def=122, env_read=35, route_call=1, route_def=23, script_def=11, script_use=4, template_file=2
**Seams:** env=104
**Grades:** anchored=104
**Orphans:** env-def-unused=33, env-use-unmatched=5, route-call-unmatched=1, route-def-uncalled=23, script-def-unused=11, template-file-unreferenced=1

### saleor
*Django e-commerce platform*

**Anchors:** env_def=88, env_read=155, route_call=39, script_def=3, script_use=9, setting_def=247, setting_read=904, task_def=121, template_file=28, template_ref=7, urlname_def=26, urlname_ref=23
**Seams:** env=20, script=1, setting=868, template=7, urlname=23
**Grades:** anchored=915, corroborated=4
**Orphans:** env-def-unused=68, env-use-unmatched=146, route-call-unmatched=39, script-def-unused=2, setting-def-unused=91, setting-use-unmatched=89, task-def-uncalled=121, template-file-unreferenced=1, urlname-def-unused=22

### saleor-dashboard
*React dashboard for Saleor*

**Anchors:** env_def=185, env_read=64, route_call=4, script_def=51, script_use=32, template_file=3
**Seams:** env=191, script=15
**Grades:** anchored=200, corroborated=6
**Orphans:** env-def-unused=130, env-use-unmatched=19, route-call-unmatched=4, script-def-unused=41

### label-studio
*Django+React data labeling*

**Anchors:** env_def=259, env_read=80, route_call=330, route_def=173, script_def=83, script_use=22, setting_def=289, setting_read=579, task_def=29, template_file=36, template_ref=30, urlname_def=175, urlname_ref=63
**Seams:** env=45, route=293, script=9, setting=668, template=30, urlname=58
**Grades:** anchored=1103
**Orphans:** env-def-unused=235, env-use-unmatched=52, route-call-unmatched=67, route-def-uncalled=126, script-def-unused=76, setting-def-unused=115, setting-use-unmatched=10, task-def-uncalled=29, template-file-unreferenced=11, urlname-def-unused=153, urlname-use-unmatched=6

### redash
*Flask+React dashboards*

**Anchors:** env_def=119, env_read=204, route_call=24, route_def=80, script_def=54, script_use=14, template_file=25, template_ref=29, urlname_def=28, urlname_ref=36
**Seams:** env=84, route=8, script=7, template=29, urlname=66
**Grades:** anchored=194
**Orphans:** env-def-unused=68, env-use-unmatched=187, route-call-unmatched=16, route-def-uncalled=75, script-def-unused=49, template-file-unreferenced=6, urlname-def-unused=20, urlname-use-unmatched=5

### plane
*Django+Next.js project management*

**Anchors:** env_def=587, env_read=239, route_call=3, route_def=386, script_def=162, script_use=9, setting_def=16, setting_read=564, task_def=47, template_file=15, template_ref=15, urlname_def=380, urlname_ref=67
**Seams:** env=782, route=5, setting=24, template=15, urlname=70
**Grades:** anchored=896
**Orphans:** env-def-unused=248, env-use-unmatched=134, route-def-uncalled=383, script-def-unused=162, setting-def-unused=14, setting-use-unmatched=552, task-def-uncalled=47, template-file-unreferenced=1, urlname-def-unused=371

### cal.com
*Next.js scheduling platform*

**Anchors:** env_def=777, env_read=917, route_call=106, route_def=87, script_def=278, script_use=42, template_file=18
**Seams:** env=3957, route=66, script=62
**Grades:** anchored=4085
**Orphans:** env-def-unused=258, env-use-unmatched=198, route-call-unmatched=43, route-call-unspecific=1, route-def-uncalled=60, script-def-unused=242, script-use-unmatched=11, template-file-unreferenced=11

### immich
*TS+Svelte photo management*

**Anchors:** env_def=237, env_read=131, route_call=8, route_def=27, script_def=123, script_use=72, task_def=3, template_file=1
**Seams:** env=44, route=4
**Grades:** anchored=48
**Orphans:** env-def-unused=211, env-use-unmatched=104, route-call-unmatched=4, route-def-uncalled=25, script-def-unused=123, script-use-unmatched=1, task-def-uncalled=3

### listmonk
*Go+Vue newsletter manager*

**Anchors:** env_def=29, env_read=6, route_call=88, script_def=24, script_use=7, template_file=31
**Seams:** script=3
**Grades:** anchored=3
**Orphans:** env-def-unused=29, env-use-unmatched=6, route-call-unmatched=88, script-def-unused=23, template-file-unreferenced=20

### maybe
*Ruby+React finance app*

**Anchors:** env_def=73, route_call=5, script_def=6, script_use=1, template_file=5
**Seams:** script=1
**Grades:** anchored=1
**Orphans:** env-def-unused=73, route-call-unmatched=5, script-def-unused=5

### documenso
*Next.js document signing*

**Anchors:** env_def=220, env_read=75, route_call=411, route_def=70, script_def=80, script_use=10
**Seams:** env=106, route=873, script=19
**Grades:** anchored=998
**Orphans:** env-def-unused=188, env-use-unmatched=30, route-call-unmatched=168, route-def-uncalled=52, script-def-unused=67

### rallly
*Next.js scheduling polls*

**Anchors:** env_def=83, env_read=163, route_call=9, route_def=37, script_def=78, script_use=1
**Seams:** env=141, route=5
**Grades:** anchored=143, corroborated=3
**Orphans:** env-def-unused=33, env-use-unmatched=86, route-call-unmatched=4, route-def-uncalled=34, script-def-unused=78

### formbricks
*Next.js survey platform*

**Anchors:** env_def=378, env_read=318, route_call=30, route_def=92, script_def=177, script_use=23, template_file=2
**Seams:** env=280, route=26, script=2
**Grades:** anchored=251, corroborated=57
**Orphans:** env-def-unused=260, env-use-unmatched=188, route-call-unmatched=4, route-def-uncalled=76, script-def-unused=175, template-file-unreferenced=1

### papermark
*Next.js document sharing*

**Anchors:** env_def=40, env_read=410, route_call=318, route_def=283, script_def=13
**Seams:** env=193, route=407
**Grades:** anchored=565, corroborated=35
**Orphans:** env-def-unused=13, env-use-unmatched=217, route-call-unmatched=37, route-call-unspecific=3, route-def-uncalled=110, script-def-unused=13

### dify
*Flask+React LLM app platform*

**Anchors:** env_def=1793, env_read=1194, route_call=315, route_def=92, script_def=135, script_use=55, setting_def=1, task_def=90, template_file=61, template_ref=1, urlname_def=23
**Seams:** env=1357, route=144, script=2
**Grades:** anchored=1503
**Orphans:** env-def-unused=731, env-use-unmatched=484, route-call-unmatched=177, route-def-uncalled=52, script-def-unused=133, setting-def-unused=1, task-def-uncalled=90, template-file-unreferenced=60, template-ref-missing=1, urlname-def-unused=23

### open-webui
*Svelte+Python chat UI*

**Anchors:** env_def=79, env_read=877, route_call=420, route_def=509, script_def=24, script_use=8, template_file=1, urlname_ref=1
**Seams:** env=33, route=63, script=4
**Grades:** anchored=74, corroborated=26
**Orphans:** env-def-unused=53, env-use-unmatched=849, route-call-unmatched=377, route-def-uncalled=473, script-def-unused=20, urlname-use-unmatched=1

### lobe-chat
*Next.js chat application*

**Anchors:** env_def=453, env_read=1799, route_call=58, route_def=120, script_def=243, script_use=90, template_file=13
**Seams:** env=2638, route=28, script=23
**Grades:** anchored=2578, corroborated=111
**Orphans:** env-def-unused=200, env-use-unmatched=1501, route-call-unmatched=32, route-def-uncalled=106, script-def-unused=240

### twenty
*TS+React CRM*

**Anchors:** env_def=319, env_read=441, route_call=285, route_def=16, script_def=176, script_use=140, template_file=8
**Seams:** env=1370, route=463, script=64
**Grades:** anchored=1897
**Orphans:** env-def-unused=206, env-use-unmatched=168, route-call-unmatched=51, route-def-uncalled=8, script-def-unused=113, script-use-unmatched=5, template-file-unreferenced=2

### infisical
*Next.js secret management*

**Anchors:** env_def=498, env_read=190, route_call=555, route_def=310, script_def=109, script_use=32, template_file=3
**Seams:** env=298, script=30
**Grades:** anchored=328
**Orphans:** env-def-unused=415, env-use-unmatched=119, route-call-unmatched=555, route-def-uncalled=310, script-def-unused=94, template-file-unreferenced=1

### hoppscotch
*Vue.js API development*

**Anchors:** env_def=119, env_read=100, route_call=30, script_def=143, script_use=29, template_file=5
**Seams:** env=79
**Grades:** anchored=79
**Orphans:** env-def-unused=101, env-use-unmatched=30, route-call-unmatched=30, script-def-unused=143
