# SJ-VIS-ENV — environment suspect or regression? (§3.3, J-V3, T-VISUAL-ENV, H§L.5)

The code pre-filter could not decide. A visual failure is an environment suspect when the images
fail with uniform anti-aliasing / font-hinting noise on screens this change could not reach.
A failure on an image whose screen the diff does reach is a `regression` until shown otherwise.
`unsure` sends it to a human as an environment question.
