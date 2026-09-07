# Article export fonts

Noto Sans SC, licensed under the accompanying SIL Open Font License.
Source: https://github.com/notofonts/noto-cjk/tree/main/Sans/Variable/TTF/Subset

`NotoSansSC.ttf` and `NotoSansSC-Bold.ttf` are static weight 400 and 700 instances
of `NotoSansSC-VF.ttf`, generated with fontTools. ReportLab subsets and embeds
the glyphs used in each PDF, so Chinese text does not depend on viewer fonts.

The static instances have distinct internal PostScript names, normalized by
`scripts/fix_export_font_names.py`. Do not retain the variable font's shared
`NotoSansSC-Thin` name: ReportLab deduplicates fonts using this internal name.
