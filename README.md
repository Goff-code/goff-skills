# goff skills

提供四种思考方式和两代图像拆层技能。在 Codex 用 `$goff-skill` 打开菜单，或直接调用其中一条。

- `$goff-1` · 第一性原理
- `$goff-2` · 先问偏好，再给三版方案
- `$goff-3` · 跨领域借鉴
- `$goff-4` · 反方检验

用 `$goff-skill 1+4` 组合使用。打开菜单后也可以说「看第 3 条原文」。

## 安装

安装五个入口，让总菜单能够找到四条提示词。

```sh
npx -y skills add Goff-code/goff-skills -a codex -g -s goff-skill -s goff-1 -s goff-2 -s goff-3 -s goff-4 -y
```

## Goff Image 图像拆层

使用 `$goff-image` 打开图像菜单，或随图片直接指定代际。

| 入口 | 全开画面验收 | 图层验收 |
| --- | --- | --- |
| `$goff-image-1` | 原图与重开的 PSD 无损导出，至少 95% 像素严格一致 | 独显、隐藏、移动主要物件，检查原被挡区域及完整素材 |
| `$goff-image-2` | 原图与重开的 PSD 无损导出，至少 99% 有效像素严格一致 | 使用同一份可编辑源文件检查上述操作 |

JPG 按解码后的像素比较，预览为无损 PNG。原图中完全被挡住的部分依结构与材质补画，单独看补画是否合理需另行验收。两个门槛均以每张图最终实测为准。

运行以下命令安装图像菜单及两代技能。

```sh
npx -y skills add Goff-code/goff-skills -a codex -g -s goff-image -s goff-image-1 -s goff-image-2 -y
```
