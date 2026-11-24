"""Generate Photoshop proof shots from the same layer manifest and object audit."""
import argparse
import json
from pathlib import Path


def make_plan(doc, audit):
    paths = set()
    groups = set()
    leaves = {}
    def visit(items, parent):
        for item in items:
            path = parent + (item['name'],)
            if path in paths:
                raise ValueError(f'Duplicate layer path: {path}')
            paths.add(path)
            if item['type'] == 'group':
                groups.add(path)
                visit(item['layers'], path)
            else:
                leaves[path] = item
    visit(doc['layers'], ())
    objects = [tuple(x) for x in audit['objects']]
    if not objects or any(p not in leaves for p in objects) or len(objects) != len(set(objects)):
        raise ValueError('Expected unique leaf paths for editable objects')
    shots = []
    seen = set()
    def shot(label, only=(), hide=(), unmask=()):
        for path in (*only, *hide, *unmask):
            if path not in paths:
                raise ValueError(f'Unknown layer path: {path}')
        key = tuple(frozenset(group) for group in (only, hide, unmask))
        if key in seen:
            return
        spec = {'file': '校样/' + label + '.png'}
        for attr, value in [('only', only), ('hide', hide), ('unmask', unmask)]:
            if value:
                spec[attr] = list(value)
        seen.add(key)
        shots.append(spec)
    shot('全开')
    for p in leaves:
        if leaves[p].get('role') == 'background':
            shot('空景', only=[p])
    for i,p in enumerate(objects, 1):
        stem = str(i).zfill(2)
        shot(stem+'-单件', only=[p])
        if leaves[p].get('mask'):
            shot(stem+'-原件', only=[p], unmask=[p])
        # Hide the broadest group containing this one object and its owned support.
        owner = next((p[:j] for j in range(1,len(p)) if p[:j] in groups
                      and sum(q[:j]==p[:j] for q in objects)==1
                      and not any(k[:j]==p[:j] and v.get('role')=='background' for k,v in leaves.items())), p)
        shot(stem+'-关闭', hide=[owner])
    for i,t in enumerate(audit['reveal'], 1):
        front = [tuple(v) for v in t['hide']]
        rear = tuple(t['rear'])
        shot(f'显露-{i}', hide=front)
        shot(f'再关后件-{i}', hide=front+[rear])
    if 'move' in audit:
        move = audit['move']
        if (tuple(move['layer']) not in paths or any(type(move[k]) is not int for k in ('dx','dy'))
                or not (move['dx'] or move['dy'])):
            raise ValueError('Move proof needs an existing layer and nonzero integer displacement')
        shots.append({'file':'校样/移动.png','move':move})
    # Text assets must be exported in their named manifest locations to support the PNG bundle.
    for p, layer in leaves.items():
        if layer.get('type')=='text' and layer.get('file'):
            shots.append({'text':list(p),'contents':layer['text'],'file':layer['file']})
    files=[s['file'] for s in shots]
    if len(set(files))!=len(files):
        raise ValueError('Duplicate proof destination; assign distinct text and proof PNG paths')
    return {'psd':doc['output'],'shots':shots}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','audit','out'):
        parser.add_argument(name,type=Path)
    args=parser.parse_args()
    if args.out.parent.resolve()!=args.manifest.parent.resolve():
        parser.error('Write proof JSON beside the layer manifest to preserve relative file paths')
    if args.out.suffix.lower()!='.json':
        parser.error('Use a new .json output path')
    try:
        data=make_plan(*(json.loads(p.read_text(encoding='utf-8-sig')) for p in (args.manifest,args.audit)))
        with args.out.open('x',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
            f.write('\n')
        print(f'Prepared {len(data["shots"])} native proof states')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(2,f'Cannot create proof plan: {exc}\n')
