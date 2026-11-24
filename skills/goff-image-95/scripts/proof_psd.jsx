#target photoshop

// Choose a proof JSON, or supply its path as $.global.posterLayerProof.
// All PSD layer paths are arrays of names, starting at the document root.
(function () {
    var argument = $.global.posterLayerProof;
    delete $.global.posterLayerProof;
    var configFile = argument ? new File(argument) : File.openDialog("选择开关核验的 proof.json");
    if (!configFile) return "Cancelled";
    #include "read_json.jsxinc"
    var config = posterLayerReadJSON(configFile);
    var parent = configFile.parent;
    var original = relativeFile(config.psd);
    if (!original.exists || !/\.(psd|psb)$/i.test(original.name)) throw Error("PSD/PSB file missing: " + original);
    if (!(config.shots instanceof Array) || !config.shots.length) throw Error("shots must be a non-empty array");

    var files = [], seen = {}, i;
    for (i = 0; i < config.shots.length; i++) {
        var shot = config.shots[i];
        if (!shot || typeof shot !== "object") throw Error("Invalid shot at index " + i);
        for (var field in shot) {
            if (shot.hasOwnProperty(field) && !/^(file|hide|only|text|contents|unmask)$/.test(field)) throw Error("Unknown shot field: " + field);
        }
        var output = relativeFile(shot.file), key = "$" + output.fsName.toLowerCase();
        if (!/\.(png|jpg)$/i.test(shot.file)) throw Error("Output must end in .png or .jpg: " + output);
        if (seen[key] || output.exists || new Folder(output.fsName).exists) throw Error("Output already exists or is repeated: " + output);
        seen[key] = true;
        files.push(output);
    }

    var dialogs = app.displayDialogs, prior = app.documents.length ? app.activeDocument : null;
    var base = null, copy = null, diskCopy = null, staged = [], published = [];
    var runId = new Date().getTime() + "-" + Math.floor(Math.random() * 1000000000);
    try {
        app.displayDialogs = DialogModes.NO;
        var count = app.documents.length, opened = app.open(original);
        if (app.documents.length > count) {
            base = opened;
        } else {
            // The user's open document may have unsaved edits. Read the actual saved bytes.
            diskCopy = new File(Folder.temp.fsName + "/poster-proof-" + new Date().getTime() +
                "-" + Math.floor(Math.random() * 1000000000) + (/\.psb$/i.test(original.name) ? ".psb" : ".psd"));
            if (diskCopy.exists) { diskCopy = null; throw Error("Temporary filename collision. Retry."); }
            if (!original.copy(diskCopy.fsName)) throw Error("Could not copy saved PSD to a temporary file");
            base = app.open(diskCopy);
        }
        var report = [Math.round(base.width.as("px")) + " x " + Math.round(base.height.as("px"))];
        for (i = 0; i < config.shots.length; i++) validateShot(base, config.shots[i]);
        for (i = 0; i < config.shots.length; i++) {
            shot = config.shots[i];
            copy = base.duplicate("Poster layer proof");
            if (shot.hide) {
                for (var j = 0; j < shot.hide.length; j++) findLayer(copy, shot.hide[j]).visible = false;
            } else if (shot.only || shot.text) {
                isolate(copy, shot.only || [shot.text], 0);
            }
            if (shot.unmask) {
                for (var u = 0; u < shot.unmask.length; u++) disableMask(findLayer(copy, shot.unmask[u]));
            }
            if (!makeFolder(files[i].parent)) throw Error("Cannot create output folder: " + files[i].parent);
            if (files[i].exists) throw Error("Refusing to overwrite: " + files[i]);
            var options;
            if (/\.png$/i.test(shot.file)) {
                options = new PNGSaveOptions();
                options.compression = 5;
            } else {
                options = new JPEGSaveOptions();
                options.quality = 11;
                options.embedColorProfile = true;
            }
            var ext = /\.png$/i.test(shot.file) ? ".png" : ".jpg";
            var temp = new File(files[i].parent.fsName + "/poster-proof-tmp-" + runId + "-" + i + ext);
            if (temp.exists || new Folder(temp.fsName).exists) throw Error("Temporary filename collision. Retry.");
            staged.push(temp);
            copy.saveAs(temp, options, true, Extension.LOWERCASE);
            if (!temp.exists || temp.length === 0) throw Error("Output was not written: " + files[i]);
            report.push(shot.file);
            copy.close(SaveOptions.DONOTSAVECHANGES);
            copy = null;
        }
        // Publish only after every view was exported. Never replace a previous run.
        for (i = 0; i < files.length; i++) {
            if (files[i].exists || new Folder(files[i].fsName).exists) throw Error("Refusing to overwrite: " + files[i]);
            if (!staged[i].rename(File.decode(files[i].name))) throw Error("Could not publish: " + files[i]);
            staged[i] = null;
            published.push(files[i]);
        }
        return report.join("\n");
    } catch (error) {
        var remaining = [], ownFiles = staged.concat(published);
        for (i = 0; i < ownFiles.length; i++) {
            var owned = ownFiles[i];
            if (owned && owned.exists && !owned.remove()) remaining.push(owned.fsName);
        }
        if (remaining.length) throw Error(String(error) + "\nCould not clean up: " + remaining.join(", "));
        throw error;
    } finally {
        try {
            if (copy) copy.close(SaveOptions.DONOTSAVECHANGES);
        } finally {
            try {
                if (base) base.close(SaveOptions.DONOTSAVECHANGES);
            } finally {
                if (diskCopy && diskCopy.exists) diskCopy.remove();
                app.displayDialogs = dialogs;
                if (prior) { try { app.activeDocument = prior; } catch (ignored) {} }
            }
        }
    }

    function relativeFile(value) {
        if (typeof value !== "string" || !value || /(^[~\/]|[\\:*?"<>|\x00-\x1F%])/.test(value))
            throw Error("Expected a relative path with / separators: " + value);
        var parts = value.split("/");
        for (var k = 0; k < parts.length; k++) {
            if (!parts[k] || /[. ]$/.test(parts[k])) throw Error("Invalid path component in " + value);
        }
        return new File(parent.fsName + "/" + value);
    }
    function makeFolder(folder) {
        return folder.exists || (folder.parent && makeFolder(folder.parent) && folder.create());
    }
    function findLayer(root, path) {
        if (!(path instanceof Array) || !path.length) throw Error("Expected non-empty layer name path");
        var cur = root;
        for (var depth = 0; depth < path.length; depth++) {
            var match = null;
            if (typeof path[depth] !== "string" || !path[depth]) throw Error("Layer names must be non-empty strings");
            if (!cur.layers) throw Error("Path descends through a non-group: " + path.join(" > "));
            for (var k = 0; k < cur.layers.length; k++) {
                var child = cur.layers[k];
                if (child.name !== path[depth]) continue;
                if (match) throw Error("Ambiguous layer: " + path.join(" > "));
                match = child;
            }
            if (!match) throw Error("Missing layer: " + path.join(" > "));
            cur = match;
        }
        return cur;
    }
    function maskLayerRef(layer) {
        var ref = new ActionReference();
        ref.putIdentifier(charIDToTypeID("Lyr "), layer.id);
        return ref;
    }
    function disableMask(layer) {
        var desc = new ActionDescriptor(), props = new ActionDescriptor();
        desc.putReference(charIDToTypeID("null"), maskLayerRef(layer));
        props.putBoolean(stringIDToTypeID("userMaskEnabled"), false);
        desc.putObject(charIDToTypeID("T   "), charIDToTypeID("Lyr "), props);
        executeAction(charIDToTypeID("setd"), desc, DialogModes.NO);
    }
    function validateShot(doc, shot) {
        if (shot.unmask !== undefined) {
            if (!(shot.unmask instanceof Array) || !shot.unmask.length) throw Error("unmask requires a non-empty list of layer paths");
            for (var u = 0; u < shot.unmask.length; u++) {
                var masked = findLayer(doc, shot.unmask[u]), desc = executeActionGet(maskLayerRef(masked));
                if (!desc.hasKey(stringIDToTypeID("hasUserMask")) || !desc.getBoolean(stringIDToTypeID("hasUserMask")))
                    throw Error("Layer has no pixel mask: " + shot.unmask[u].join(" > "));
            }
        }
        var modes = Number(shot.hide !== undefined) + Number(shot.only !== undefined) + Number(shot.text !== undefined);
        if (modes > 1) throw Error("Choose one of hide, only or text: " + shot.file);
        if (shot.contents !== undefined && shot.text === undefined) throw Error("contents requires a text path: " + shot.file);
        if (shot.text !== undefined) {
            var textLayer = findLayer(doc, shot.text);
            if (!/\.png$/i.test(shot.file) || textLayer.typename !== "ArtLayer" || textLayer.kind !== LayerKind.TEXT)
                throw Error("text requires a Photoshop text layer and a .png output: " + shot.file);
            if (shot.contents !== undefined && (typeof shot.contents !== "string" ||
                textLayer.textItem.contents !== shot.contents.replace(/\r\n|\r|\n/g, "\r")))
                throw Error("Saved text differs from expected contents: " + shot.text.join(" > "));
        } else if (modes) {
            var paths = shot.hide !== undefined ? shot.hide : shot.only;
            if (!(paths instanceof Array) || !paths.length) throw Error("Expected a non-empty list of layer paths");
            for (var k = 0; k < paths.length; k++) findLayer(doc, paths[k]);
        }
    }
    function isolate(node, paths, depth) {
        for (var k = 0; k < node.layers.length; k++) {
            var layer = node.layers[k], whole = false, nested = [];
            for (var n = 0; n < paths.length; n++) {
                if (paths[n][depth] !== layer.name) continue;
                if (paths[n].length === depth + 1) whole = true;
                else nested.push(paths[n]);
            }
            layer.visible = whole || nested.length > 0;
            // An explicitly selected group retains its children's saved visibility.
            if (!whole && nested.length) isolate(layer, nested, depth + 1);
        }
    }
}());
