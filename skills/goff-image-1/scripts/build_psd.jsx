#target photoshop
// Run under File > Scripts > Browse, or set $.global.posterLayerManifest before $.evalFile.
(function () {
    var argument = $.global.posterLayerManifest;
    delete $.global.posterLayerManifest;
    var manifestFile = argument ? new File(argument) : File.openDialog("选择拆层 JSON 清单");
    if (!manifestFile) return "已取消";

    #include "read_json.jsxinc"

    function relativeFile(path, extension) {
        if (typeof path !== "string" || !extension.test(path) ||
            /(^\/|\\|:|(^|\/)\.\.(\/|$)|%[0-9a-f]{2})/i.test(path))
            throw Error("清单中应填写相对路径（使用 /） " + path);
        return new File(manifestFile.parent.fsName + "/" + path);
    }
    function numeric(n, field) {
        if (typeof n !== "number" || !isFinite(n)) throw Error("无效数值 " + field);
        return n;
    }
    function px(n) { return UnitValue(n, "px"); }
    function bounds(layer) {
        var b = layer.bounds;
        return [b[0].as("px"), b[1].as("px"), b[2].as("px"), b[3].as("px")];
    }
    var spec = posterLayerReadJSON(manifestFile);
    var output = relativeFile(spec.output, /\.psd$/i);
    if (!output.parent.exists) throw Error("请先建立输出目录 " + output.parent.fsName);
    if (output.exists) throw Error("已存在同名 PSD，请指定新版本名 " + output.fsName);
    var w = numeric(spec.width, "width"), h = numeric(spec.height, "height");
    if (w < 1 || h < 1 || w !== Math.floor(w) || h !== Math.floor(h)) throw Error("无效画布尺寸");
    var resolution = spec.resolution === undefined ? 72 : numeric(spec.resolution, "resolution");
    if (resolution <= 0) throw Error("resolution 应大于 0");
    function checkSize(doc) {
        if (doc.width.as("px") !== w || doc.height.as("px") !== h)
            throw Error("画布尺寸不符 " + doc.name + "，预期 " + w + " × " + h);
    }
    function freshFile(dir, ext) {
        var file;
        do { file = new File(dir.fsName + "/poster-layer-" + new Date().getTime() + "-" +
                Math.floor(Math.random() * 1000000000) + ext); } while (file.exists);
        return file;
    }
    var previous = app.documents.length ? app.activeDocument : null;
    var oldDialogs = app.displayDialogs, oldUnits = app.preferences.rulerUnits, oldText = app.preferences.typeUnits;
    var target = null, reopened = null, staged = null;

    function readPNG(pathname, consume) {
        var file = relativeFile(pathname, /\.png$/i);
        if (!file.exists) throw Error("找不到素材 " + file.fsName);
        var scratch = null, opened = null, count = app.documents.length;
        // If an input is already open (possibly with unsaved edits), read a private disk copy.
        for (var j = 0; j < app.documents.length; j++) {
            var path = "";
            try { path = app.documents[j].fullName.fsName; } catch (e) {}
            if (path.toLowerCase() === file.fsName.toLowerCase()) {
                scratch = freshFile(Folder.temp, ".png");
                if (!file.copy(scratch)) throw Error("无法读取素材副本 " + file.fsName);
                file = scratch; break;
            }
        }
        try {
            opened = app.open(file);
            if (app.documents.length !== count + 1) {
                opened = null;
                throw Error("Photoshop 使用了已打开的素材，无法从磁盘核验 " + file.fsName);
            }
            checkSize(opened);
            return consume(opened);
        } finally {
            if (opened) opened.close(SaveOptions.DONOTSAVECHANGES);
            if (scratch && scratch.exists) scratch.remove();
        }
    }
    var c = charIDToTypeID, sid = stringIDToTypeID;
    function layerRef(layer) {
        var ref = new ActionReference();
        ref.putIdentifier(c("Lyr "), layer.id);
        return ref;
    }
    function setMaskEnabled(layer, state) {
        var edit = new ActionDescriptor(), props = new ActionDescriptor();
        edit.putReference(c("null"), layerRef(layer));
        props.putBoolean(sid("userMaskEnabled"), state);
        edit.putObject(c("T   "), c("Lyr "), props);
        executeAction(c("setd"), edit, DialogModes.NO);
    }
    function addMask(node, layer) {
        var source = readPNG(node.mask, function (opened) {
            if (opened.mode !== DocumentMode.GRAYSCALE || opened.bitsPerChannel !== BitsPerChannelType.EIGHT ||
                opened.channels.length !== 1 || !opened.activeLayer.isBackgroundLayer)
                throw Error("蒙版需使用无 alpha 的 8 位灰度 PNG " + node.mask);
            return opened.channels[0].duplicate(target);
        });
        app.activeDocument = target;
        target.activeLayer = layer;
        // A temporary alpha channel retains the grayscale samples and their full-canvas position.
        // Apply Image writes to the native mask without selections, clipboard, or color conversion.
        try {
            target.activeChannels = target.componentChannels;
            var make = new ActionDescriptor(), where = new ActionReference();
            make.putClass(c("Nw  "), c("Chnl"));
            where.putEnumerated(c("Chnl"), c("Chnl"), c("Msk "));
            make.putReference(c("At  "), where);
            make.putEnumerated(c("Usng"), c("UsrM"), c("RvlA"));
            executeAction(c("Mk  "), make, DialogModes.NO);
            var select = new ActionDescriptor();
            select.putReference(c("null"), where);
            select.putBoolean(c("MkVs"), false);
            executeAction(c("slct"), select, DialogModes.NO);
            var apply = new ActionDescriptor(), blend = new ActionDescriptor(), from = new ActionReference();
            from.putName(c("Chnl"), source.name);
            blend.putReference(c("T   "), from);
            blend.putEnumerated(c("Clcl"), c("Clcn"), c("Nrml"));
            blend.putBoolean(c("PrsT"), false);
            apply.putObject(c("With"), c("Clcl"), blend);
            executeAction(c("AppI"), apply, DialogModes.NO);
        } finally {
            source.remove();
            target.activeChannels = target.componentChannels;
        }
    }
    function raster(node) {
        var before;
        var layer = readPNG(node.file, function (opened) {
            before = bounds(opened.activeLayer);
            return opened.activeLayer.duplicate(target, ElementPlacement.PLACEATBEGINNING);
        });
        app.activeDocument = target;
        var after = bounds(layer);
        if (after[0] !== before[0] || after[1] !== before[1])
            layer.translate(px(before[0] - after[0]), px(before[1] - after[1]));
        if (node.mask !== undefined) addMask(node, layer);
        node.expectedBounds = before;
        return layer;
    }
    function content(node) { return node.text.replace(/\r\n|\r|\n/g, "\r"); }
    function typeLayer(node, parent) {
        if (typeof node.text !== "string" || !node.text.length ||
            typeof node.font !== "string" || !node.font ||
            !/^#?[a-f0-9]{6}$/i.test(node.color || "")) throw Error("文字配置不完整 " + node.name);
        var size = numeric(node.sizePx, "sizePx");
        if (size <= 0) throw Error("字号须大于 0");
        var font;
        try { font = app.fonts.getByName(node.font); } catch (e) { throw Error("缺少字体 " + node.font); }
        if (!font || font.postScriptName !== node.font) throw Error("缺少字体 " + node.font);
        var layer = parent.artLayers.add();
        layer.kind = LayerKind.TEXT;
        var item = layer.textItem, color = new SolidColor();
        item.kind = TextType.POINTTEXT;
        item.justification = Justification.LEFT;
        item.font = font.postScriptName;
        item.size = UnitValue(size * 72 / resolution, "pt");
        item.contents = content(node);
        if (node.tracking !== undefined) item.tracking = numeric(node.tracking, "tracking");
        if (node.leadingPx !== undefined) {
            item.useAutoLeading = false;
            item.leading = UnitValue(numeric(node.leadingPx, "leadingPx") * 72 / resolution, "pt");
        }
        item.position = [px(numeric(node.x, "x")), px(numeric(node.y, "y"))];
        color.rgb.hexValue = node.color.replace(/^#/, "");
        item.color = color;
        return layer;
    }
    function addStack(nodes, parent) {
        if (!(nodes instanceof Array) || !nodes.length) throw Error("图层列表为空");
        for (var k = 0; k < nodes.length; k++) {
            var n = nodes[k], top = parent.layers.length ? parent.layers[0] : null, layer;
            if (!n || typeof n.name !== "string" || !n.name.length) throw Error("图层缺少名称");
            if (n.mask !== undefined && n.type !== "raster") throw Error("仅像素图层支持 mask " + n.name);
            if (n.type === "group") layer = parent.layerSets.add();
            else if (n.type === "raster") layer = raster(n);
            else if (n.type === "text") layer = typeLayer(n, parent);
            else throw Error("未知图层类型 " + n.type);
            layer.name = n.name;
            if (top) layer.move(top, ElementPlacement.PLACEBEFORE);
            else if (parent.typename === "LayerSet" && n.type === "raster")
                layer.move(parent, ElementPlacement.INSIDE);
            if (n.type === "group") addStack(n.layers, layer);
        }
    }
    function verify(nodes, parent) {
        if (nodes.length !== parent.layers.length) throw Error("复开后图层数不同 " + parent.name);
        for (var k = 0; k < nodes.length; k++) {
            var n = nodes[k], layer = parent.layers[nodes.length - k - 1];
            if (layer.name !== n.name) throw Error("复开后图层顺序不同 " + n.name);
            if (n.type === "group") {
                if (layer.typename !== "LayerSet") throw Error("缺少图层组 " + n.name);
                verify(n.layers, layer);
            } else if (n.type === "text") {
                if (layer.kind !== LayerKind.TEXT || layer.textItem.contents !== content(n) ||
                    layer.textItem.font !== n.font) throw Error("文字图层复核失败 " + n.name);
            } else {
                var masked = n.mask !== undefined;
                if (masked) {
                    var saved = executeActionGet(layerRef(layer));
                    if (!saved.getBoolean(sid("hasUserMask")) || !saved.getBoolean(sid("userMaskEnabled")) ||
                        !saved.getBoolean(sid("userMaskLinked"))) throw Error("复开后未找到已启用且链接的像素蒙版 " + n.name);
                    setMaskEnabled(layer, false);
                }
                try {
                    if (bounds(layer).join(",") !== n.expectedBounds.join(","))
                        throw Error("素材原件的位置或边界复核失败 " + n.name);
                } finally {
                    if (masked) setMaskEnabled(layer, true);
                }
            }
        }
    }
    try {
        app.displayDialogs = DialogModes.NO;
        app.preferences.rulerUnits = Units.PIXELS;
        app.preferences.typeUnits = TypeUnits.POINTS;
        target = app.documents.add(px(w), px(h), resolution, "海报拆层", NewDocumentMode.RGB,
            DocumentFill.TRANSPARENT, 1, BitsPerChannelType.EIGHT, "sRGB IEC61966-2.1");
        var empty = target.activeLayer;
        addStack(spec.layers, target);
        empty.remove();
        staged = freshFile(output.parent, ".psd");
        var options = new PhotoshopSaveOptions();
        options.layers = true;
        options.embedColorProfile = true;
        options.maximizeCompatibility = true;
        target.saveAs(staged, options, true, Extension.LOWERCASE);
        target.close(SaveOptions.DONOTSAVECHANGES); target = null;
        reopened = app.open(staged);
        checkSize(reopened);
        verify(spec.layers, reopened);
        reopened.close(SaveOptions.DONOTSAVECHANGES); reopened = null;
        if (output.exists || !staged.rename(File.decode(output.name))) throw Error("无法存入新 PSD " + output.fsName);
        staged = null;
        return output.fsName;
    } finally {
        if (reopened) reopened.close(SaveOptions.DONOTSAVECHANGES);
        if (target) target.close(SaveOptions.DONOTSAVECHANGES);
        if (staged && staged.exists) staged.remove();
        app.preferences.typeUnits = oldText;
        app.preferences.rulerUnits = oldUnits;
        app.displayDialogs = oldDialogs;
        if (previous) app.activeDocument = previous;
    }
})();
