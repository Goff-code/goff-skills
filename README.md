# goff skills

提供四种思考方式和两档图像拆层技能。在 Codex 用 `$goff-skill` 打开菜单，或直接调用其中一条。

- `$goff-think-1` · 第一性原理
- `$goff-think-2` · 先问再做
- `$goff-think-3` · 跨领域借鉴
- `$goff-think-4` · 反方检验

用 `$goff-skill 1+4` 组合使用。打开菜单后也可以说「看第 3 条原文」。

## 安装与调用

一条命令安装整套技能。在 Codex 输入 `$goff-skill` 打开总菜单，选择思考方式或图像拆层。

```sh
npx -y skills add Goff-code/goff-skills -a codex -g -s goff-skill -s goff-think-1 -s goff-think-2 -s goff-think-3 -s goff-think-4 -s goff-image -s goff-image-95 -s goff-image-99 -y
```

## 图像拆层

| 菜单名称 | 直接调用 | 全开像素一致率目标 |
| --- | --- | --- |
| goff-image-95% | `$goff-image-95` | 至少 95% |
| goff-image-99% | `$goff-image-99` | 至少 99% |

也可以随图输入 `$goff-skill 99%`，或用 `$goff-image` 只查看拆图选项。两档都输出完整可编辑素材、分层 PSD 和关层校样。一致率按原图与重开 PSD 后导出的无损 PNG 实测。
