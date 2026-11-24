# 组装与核验

这些脚本负责素材准备完毕后的步骤。PSD 装配与开关导出需要本地 Photoshop。PNG 检查和打包需要 Python 3 与 Pillow。优先用已装好 Pillow 的 Python，可用 `python3 -c "import PIL"` 检查。没有 Photoshop 时，可先交付对齐 PNG 和预览；只有实际写出并验证过的 PSD、文字层和开关状态才列入交付。

## 准备同一份素材清单

在新版本工作目录创建 `layers.json`。所有文件路径以各自 JSON 的目录为起点，用 `/` 分隔。素材放在其下，先建立输出目录。以下是字段示例，把尺寸、路径、字体和各组替换为本图的实测值。

```json
{
  "width": 1200, "height": 1600, "resolution": 72,
  "output": "交付/海报-v01.psd",
  "layers": [
    {"type":"raster","name":"完整底景","role":"background","file":"素材/bg.png"},
    {"type":"group","name":"商品","layers":[
      {"type":"raster","name":"落影","file":"素材/shadow.png"},
      {"type":"raster","name":"杯身","file":"素材/cup.png"},
      {"type":"raster","name":"杯贴","file":"素材/完整杯贴.png","mask":"蒙版/杯贴印刷边界.png"}
    ]},
    {"type":"raster","name":"倾倒壶与液流","file":"素材/pour.png"},
    {"type":"group","name":"版面文案","layers":[
      {"type":"text","name":"副标题","text":"牛油果饮品","font":"STKaitiSC-Regular",
       "sizePx":42,"x":66,"y":180,"color":"#EFE7AA","file":"文字导出/subtitle.png"}
    ]}
  ]
}
```

数组从底到顶，同一父级中图层名称唯一。背景通常为铺满整幅的不透明 PNG。原本透明的素材用根字段 `"transparentBackground":true`，可只列一个透明像素层。组可嵌套。每张素材含透明边距并与原画布对齐。文字 `x,y` 表示左对齐的起笔位置和基线，`sizePx` 为原图像素字号，`font` 为本机可用的 PostScript 字体名；另支持 `tracking` 与 `leadingPx`。字体替代须以视觉对照复核并说明。此辅助装配器生成 8 位 sRGB 像素层、组和点文字。若输入为高位深或其他色域，先决定是否需要保留原配置；需保留时走支持原位深、色域的 Photoshop 原生流程。需要复杂排版、矢量蒙版或跨组联动时，也可以用 Photoshop 原生能力补充。

填写 `text.file` 时可以直接指向下一步要导出的 PNG。预检会提示哪些文字 PNG 待生成，构建 PSD 时仍会创建真正的文字层。完成文字导出后，同一份清单即可打包。全幅半透明雾光一类有意覆盖整个画布的素材可指定 `role:"overlay"`；普通物件须留出透明区域。

## 原件与像素蒙版

像素层的可选 `mask` 指向清单目录下的 **8 位灰度 PNG**。蒙版与原画布等大，保存为单通道灰度，移除 alpha 通道。白色显示原件，黑色隐藏，灰色按比例显示。图层的 `file` 保存带完整外轮廓、孔洞和柔边的原位素材。构建时 Photoshop 将灰度写入原生像素蒙版，默认启用并与素材链接。重开检查会确认蒙版存在、启用且链接，并在校验副本中暂时停用蒙版，核对完整原件的位置和边界。

杯身挡住背景、液流挡住杯口等普通前后关系，直接用层序表达。下层保留完整的背景和杯口，隐藏上层即可看到它们。局部裁边或同一元素在另一物体前后穿插时，再给相应部分加蒙版。例中的杯贴按印刷边界裁切。需要查看原件时，在 Photoshop 中按住 Shift 点击蒙版缩略图以暂时停用。

PNG 包中的常规图层可按编号直接叠放。含蒙版的图层默认使用蒙版生效后的透明度。包内另有 `蒙版源件/层级与层名/完整原件.png` 和 `显示蒙版.png`，分别保留原始素材文件和可独立修改的灰度图。

## 从 PSD 真实导出开关图

在同一工作目录准备 `proof.json`，按本图遮挡清单设置。每个数组是从根组开始的准确图层路径。

```json
{
  "psd":"交付/海报-v01.psd",
  "shots":[
    {"file":"校样/全开.png"},
    {"file":"校样/移开商品.jpg","hide":[["商品"]]},
    {"file":"校样/纯背景.jpg","only":[["完整底景"]]},
    {"file":"校样/单独杯身.png","only":[["商品","杯身"]]},
    {"file":"校样/杯贴印刷态.png","only":[["商品","杯贴"]]},
    {"file":"校样/完整杯贴.png","only":[["商品","杯贴"]],"unmask":[["商品","杯贴"]]},
    {"file":"校样/杯口显露.png","hide":[["倾倒壶与液流"]]},
    {"file":"校样/杯口参照.png","hide":[["倾倒壶与液流"],["商品"]]},
    {"file":"文字导出/subtitle.png","text":["版面文案","副标题"],"contents":"牛油果饮品"}
  ]
}
```

JPEG 适合完整场景，透明素材或透明底作品的校样使用 PNG。文字型导出同时检查目标的文字图层类型，可用 `contents` 校对原文。核验后逐张看图，特别放大前后轮廓交叉的位置。

`unmask` 接受图层路径列表，可单用，也可搭配 `only` 或 `hide`。导出完整原件时使用 `only` 配合 `unmask`。每张图在独立副本中导出，保存的 PSD 维持默认蒙版状态。验收正常隐藏动作时保留默认蒙版设置。

### 验证遮挡处有可显露的素材

对同一份重开的 PSD 导出两张原尺寸 PNG。第一张关掉遮挡者，第二张在此基础上再关掉被挡者及其对应组。两张仅改变这一组的开关。导出前，在原图实际被挡住的位置选定一个或几个矩形，例如液流覆盖的杯口内侧或茶桌挡住的动物胸腹。矩形尽量落在预计能显露内容的内部。按预期覆盖面积设定最低百分比，下例坐标与阈值仅示意。

```text
<python> <skill>/scripts/check_reveal.py 校样/杯口显露.png 校样/杯口参照.png --roi "杯口遮挡处:585,675,36,16" --min-percent 50 --min-delta 8 --json 校样/遮挡显露报告.json
```

坐标为从左上角计算的 `X,Y,宽,高`，可多次传 `--roi`。脚本在纯黑和纯白衬底上各比较一次渲染颜色，用较大的通道差衡量实际可见变化。默认每通道至少相差 8 阶才计入，完全透明区域里的 RGB 不计入。每个矩形都须独自达到预定覆盖比例。开启后景物件使某个像素的 alpha 比参照图下降达到该差值时，这一矩形也会失败，应检查图层开关或异常挖空。返回码 0 表示通过，1 表示显露不足或出现异常透明度损失，2 表示输入条件有误。最后查看显露处的材质、轮廓和连接方向，确认所见内容确实属于被挡物体。

## 执行

以下命令中的 `<skill>` 代表当前 SKILL.md 所在目录，`<python>` 代表带 Pillow 的 Python。先建立新的版本目录，保持每次的校样与本次 PSD 对应。

```text
<python> <skill>/scripts/check_assets.py layers.json --source 原稿.jpg
python3 <skill>/scripts/run_photoshop.py build layers.json
python3 <skill>/scripts/run_photoshop.py proof proof.json
<python> <skill>/scripts/check_fidelity.py 原稿.jpg 校样/全开.png --min-exact 95 --json 校样/保真报告.json
<python> <skill>/scripts/check_assets.py layers.json --source 原稿.jpg --zip 分层PNG素材-v01.zip
```

中间两步是 macOS 用法。也可以在 Photoshop「文件 → 脚本 → 浏览」依次运行 `scripts/build_psd.jsx` 和 `scripts/proof_psd.jsx` 并选取各自的 JSON；运行时让 `read_json.jsxinc` 与它们保持同目录。构建脚本会从磁盘重开 PSD 检查层序、名称、像素层位置和文字内容。对照图从重开后的 PSD 导出，直接排成一张图供用户比较。
