# goff skills

四条按需调用的思考提示词。在 Codex 用 `$goff-skill` 打开菜单，或直接调用其中一条。

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
