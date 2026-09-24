import { useRef, useState } from 'react';
import type { DragEvent, ReactNode } from 'react';
import { Archive, Download, Eye, File as FileIcon, FileImage, FileText, ImagePlus, Palette, Replace, Star, Trash2, TriangleAlert, Upload } from 'lucide-react';
import { Badge, IconButton } from './ui';
import './ProductAssetSections.css';

/**
 * 产品资料里的文件区块：产品照片、产品规格书、包装与标签。
 * 这里只负责展示和交互；上传、保存、权限都在 ProductMasterPage 里。
 */
export type AssetItem = { id: string; field: string; repetition: number; filename: string; mimeType: string; size: number; sortOrder?: number };
export type AssetField = { name: string; maxRepeat: number };
export type AssetEnv = {
  assets: AssetItem[];
  previews: Record<string, string>;
  previewErrors: Record<string, string>;
  readOnly: boolean;
  /** 当前账号可以增删文件 */
  editable: boolean;
  busy: boolean;
  /** 产品还没保存过，服务器没有地方存文件 */
  unsaved: boolean;
  /** 已经写进服务器的版本里（否则是本次编辑新加的） */
  isSaved: (asset: AssetItem) => boolean;
  /** 只在本地草稿里的文件，可以直接从浏览器下载 */
  isLocal: (asset: AssetItem) => boolean;
  onPreview: (asset: AssetItem) => void;
  onDownload: (asset: AssetItem) => void;
  onRemove: (asset: AssetItem) => void;
  onImageError: (asset: AssetItem) => void;
};

export const MAIN_PHOTO_FIELD = 'image_main';
export const PHOTO_ACCEPT = 'image/jpeg,image/png,image/webp,image/gif';
export const SPEC_ACCEPT = `${PHOTO_ACCEPT},application/pdf`;
const IMAGE_TYPE = /^image\/(png|jpeg|webp|gif)$/;
const PACKAGING_LABELS: Record<string, string> = { 彩盒: '彩盒', 外紙箱: '外纸箱', 貼紙: '贴纸', 標籤檔案: '标签文件', 標籤檔案後: '标签文件（后）', 發料標籤檔案: '发料标签文件' };

const isImage = (a: AssetItem) => IMAGE_TYPE.test(a.mimeType);
const isPdf = (a: AssetItem) => a.mimeType === 'application/pdf';
const canPreview = (a: AssetItem) => isImage(a) || isPdf(a);
const extensionOf = (a: AssetItem) => a.filename.match(/\.([a-z0-9]{1,10})$/i)?.[1] ?? '';
function formatSize(bytes: number) { return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`; }
function fileKind(a: AssetItem): { label: string; icon: ReactNode } {
  const ext = extensionOf(a);
  const label = ext ? ext.toUpperCase() : '文件';
  if (isImage(a) || /^(png|jpe?g|webp|gif|bmp|heic|tiff?)$/i.test(ext)) return { label, icon: <FileImage aria-hidden="true" /> };
  if (isPdf(a) || /^(docx?|xlsx?|pptx?|txt|csv|pages|numbers|key)$/i.test(ext)) return { label, icon: <FileText aria-hidden="true" /> };
  if (/^(zip|rar|7z|tar|gz|tgz|bz2)$/i.test(ext)) return { label, icon: <Archive aria-hidden="true" /> };
  if (/^(ai|psd|cdr|eps|indd|svg|sketch|fig|xd|dxf|dwg)$/i.test(ext)) return { label, icon: <Palette aria-hidden="true" /> };
  return { label, icon: <FileIcon aria-hidden="true" /> };
}
function bySlot(assets: AssetItem[], order: string[]) {
  return assets.filter(a => order.includes(a.field)).sort((a, b) => order.indexOf(a.field) - order.indexOf(b.field));
}

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files');
/** 拖入文件的落点：进入/离开会在子元素间反复触发，用计数器判断是否还在区域内。 */
function useDropZone(enabled: boolean, onFiles: (files: File[]) => void) {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  return {
    over: over && enabled,
    bind: {
      onDragEnter: (e: DragEvent) => { if (!hasFiles(e)) return; e.preventDefault(); depth.current += 1; setOver(true); },
      onDragOver: (e: DragEvent) => { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = enabled ? 'copy' : 'none'; },
      onDragLeave: () => { depth.current = Math.max(0, depth.current - 1); if (!depth.current) setOver(false); },
      onDrop: (e: DragEvent) => {
        if (!hasFiles(e)) return;
        e.preventDefault(); depth.current = 0; setOver(false);
        const files = Array.from(e.dataTransfer.files);
        if (enabled && files.length) onFiles(files);
      },
    },
  };
}

function Frame({ title, meta, hint, children }: { title: string; meta?: string; hint?: string; children: ReactNode }) {
  return <section className="pm-card">
    <div className="pm-card-head"><i className="pm-card-rule" /><h2>{title}</h2>{meta && <div className="pm-card-meta">{meta}</div>}</div>
    <div className="pm-card-body pa-body">
      {hint && <p className="pa-hint">{hint}</p>}
      {children}
    </div>
  </section>;
}

function Note({ children }: { children: ReactNode }) {
  return <p className="pa-note" role="status"><TriangleAlert aria-hidden="true" /><span>{children}</span></p>;
}

type DropCellProps = {
  enabled: boolean;
  /** false：拖放由外层容器处理，这里只保留点击选择 */
  dropOn?: boolean;
  multiple?: boolean;
  accept?: string;
  title: string;
  hint?: string;
  variant: 'wide' | 'tile' | 'slim';
  icon?: ReactNode;
  onFiles: (files: File[]) => void;
};
function DropCell({ enabled, dropOn = true, multiple = false, accept, title, hint, variant, icon, onFiles }: DropCellProps) {
  const zone = useDropZone(enabled && dropOn, onFiles);
  return <label className={`pa-drop pa-drop-${variant}${zone.over ? ' is-over' : ''}${enabled ? '' : ' is-disabled'}`} {...(dropOn ? zone.bind : {})}>
    {icon ?? <Upload aria-hidden="true" />}
    <span className="pa-drop-text">
      <span className="pa-drop-title">{title}</span>
      {hint && <span className="pa-drop-hint">{hint}</span>}
    </span>
    <input type="file" className="pa-file-input" multiple={multiple} accept={accept} disabled={!enabled} aria-label={title}
      onChange={e => { const files = Array.from(e.target.files ?? []); e.target.value = ''; if (files.length) onFiles(files); }} />
  </label>;
}

function ReplaceTool({ accept, disabled, onFile }: { accept?: string; disabled: boolean; onFile: (file: File) => void }) {
  return <label className={`ui-button ui-icon-button pa-tool pa-tool-file${disabled ? ' is-disabled' : ''}`} title="替换文件">
    <Replace aria-hidden="true" />
    <input type="file" className="pa-file-input" accept={accept} disabled={disabled} aria-label="替换文件"
      onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) onFile(file); }} />
  </label>;
}

function uploadTitle(env: AssetEnv, idle: string) {
  return env.unsaved ? '保存产品资料后即可上传' : env.busy ? '正在处理…' : idle;
}

/* ── 产品照片 ───────────────────────────────────────────────────── */

function PhotoTile<F extends AssetField>({ asset, position, isMain, field, env, onReplace, onSetMain }: {
  asset: AssetItem; position: number; isMain: boolean; field?: F; env: AssetEnv;
  onReplace: (file: File, field: F) => void; onSetMain: (asset: AssetItem) => void;
}) {
  const src = env.previews[asset.id];
  const failed = env.previewErrors[asset.id];
  const showImage = !!src && !failed && isImage(asset);
  const fallback = failed ? '预览加载失败' : !isImage(asset) ? `${fileKind(asset).label} 格式暂不支持预览` : '载入中…';
  const editable = env.editable && !env.readOnly;
  return <figure className={`pa-tile${isMain ? ' pa-tile-hero' : ''}`}>
    <button type="button" className="pa-tile-media" onClick={() => env.onPreview(asset)} aria-label={`预览 ${asset.filename}`} title={asset.filename}>
      {showImage ? <img src={src} alt={asset.filename} onError={() => env.onImageError(asset)} /> : <span className="pa-tile-fallback">{fallback}</span>}
    </button>
    <figcaption className="pa-tile-bar">
      {isMain ? <Badge tone="accent">主图</Badge> : <span className="pa-tile-n">{String(position).padStart(2, '0')}</span>}
      <span className="pa-tools">
        <IconButton className="pa-tool" label="预览" onClick={() => env.onPreview(asset)}><Eye /></IconButton>
        {editable && !isMain && <IconButton className="pa-tool" label="设为主图" disabled={env.busy} onClick={() => onSetMain(asset)}><Star /></IconButton>}
        {editable && field && <ReplaceTool accept={PHOTO_ACCEPT} disabled={env.busy} onFile={file => onReplace(file, field)} />}
        {editable && <IconButton className="pa-tool" label="移除" disabled={env.busy} onClick={() => env.onRemove(asset)}><Trash2 /></IconButton>}
      </span>
    </figcaption>
  </figure>;
}

/** 照片逐张添加：只显示已有的图和一个「添加」格；第一张（或被指定的一张）是主图。 */
export function PhotoSection<F extends AssetField>({ title, fields, env, onAdd, onReplace, onSetMain }: {
  title: string; fields: F[]; env: AssetEnv;
  onAdd: (files: File[]) => void; onReplace: (file: File, field: F) => void; onSetMain: (asset: AssetItem) => void;
}) {
  const order = fields.map(f => f.name);
  const photos = bySlot(env.assets, order);
  const main = photos.find(a => a.field === MAIN_PHOTO_FIELD);
  const others = photos.filter(a => a !== main);
  const editable = env.editable && !env.readOnly;
  const canAdd = editable && !env.unsaved && !env.busy && photos.length < fields.length;
  const zone = useDropZone(canAdd, onAdd);
  const fieldOf = (a: AssetItem) => fields.find(f => f.name === a.field);

  if (!fields.length) return null;
  if (env.readOnly && !photos.length) return <Frame title={title}><p className="pa-empty">暂无产品照片。</p></Frame>;
  return <Frame title={title}
    meta={env.readOnly ? `${photos.length} 张图片` : `${photos.length} / ${fields.length} 张`}
    hint={editable ? `第一张是主图，会作为产品缩略图显示；想换主图，点其他图片上的星标。可一次拖入多张，最多 ${fields.length} 张。` : undefined}>
    {editable && env.unsaved && <Note>请先保存产品资料，之后才能上传图片。</Note>}
    {editable && photos.length > 0 && !main && <Note>已有产品照片但还没有主图。请在下面选一张，点它的星标设为主图，否则无法保存。</Note>}
    <div className={`pa-photo-body${zone.over ? ' is-over' : ''}`} {...zone.bind}>
      {!photos.length
        ? editable
          ? <DropCell variant="wide" dropOn={false} enabled={canAdd} multiple accept={PHOTO_ACCEPT} icon={<ImagePlus aria-hidden="true" />}
              title={uploadTitle(env, '拖入产品照片，或点击选择')} hint={env.unsaved ? undefined : '第一张会成为主图 · 可一次选多张 · JPG / PNG / WebP / GIF'} onFiles={onAdd} />
          : <p className="pa-empty">暂无产品照片。</p>
        : <div className="pa-photo-grid">
            {main
              ? <PhotoTile asset={main} position={1} isMain field={fieldOf(main)} env={env} onReplace={onReplace} onSetMain={onSetMain} />
              : <div className="pa-tile pa-tile-hero pa-tile-missing"><TriangleAlert aria-hidden="true" /><span>未设主图</span></div>}
            {others.map(a => <PhotoTile key={a.id} asset={a} position={photos.indexOf(a) + 1} isMain={false} field={fieldOf(a)} env={env} onReplace={onReplace} onSetMain={onSetMain} />)}
            {editable && photos.length < fields.length && <DropCell variant="tile" dropOn={false} enabled={canAdd} multiple accept={PHOTO_ACCEPT} icon={<ImagePlus aria-hidden="true" />}
              title={uploadTitle(env, '添加图片')} hint={env.unsaved || env.busy ? undefined : '拖入或点击选择'} onFiles={onAdd} />}
          </div>}
    </div>
  </Frame>;
}

/* ── 文件行（规格书、包装与标签共用） ────────────────────────────── */

function FileRow<F extends AssetField>({ asset, label, field, accept, env, onReplace }: {
  asset: AssetItem; label?: string; field?: F; accept?: string; env: AssetEnv; onReplace?: (file: File, field: F) => void;
}) {
  const kind = fileKind(asset);
  const src = env.previews[asset.id];
  const failed = env.previewErrors[asset.id];
  const editable = env.editable && !env.readOnly;
  return <div className="pa-file">
    <div className="pa-file-icon">
      {isImage(asset) && src && !failed ? <img src={src} alt="" onError={() => env.onImageError(asset)} /> : kind.icon}
    </div>
    <div className="pa-file-meta">
      {label && <span className="pa-file-label">{label}</span>}
      <b title={asset.filename}>{asset.filename}</b>
      <span className="pa-file-sub">
        <span>{kind.label} · {formatSize(asset.size)}</span>
        {!env.isSaved(asset) && <Badge tone="warning">待保存</Badge>}
        {failed && <span className="pa-file-error">{failed}</span>}
      </span>
    </div>
    <span className="pa-tools">
      {canPreview(asset) && <IconButton className="pa-tool" label="预览" onClick={() => env.onPreview(asset)}><Eye /></IconButton>}
      {(env.isSaved(asset) || env.isLocal(asset)) && <IconButton className="pa-tool" label="下载" onClick={() => env.onDownload(asset)}><Download /></IconButton>}
      {editable && field && onReplace && <ReplaceTool accept={accept} disabled={env.busy} onFile={file => onReplace(file, field)} />}
      {editable && <IconButton className="pa-tool" label="移除" disabled={env.busy} onClick={() => env.onRemove(asset)}><Trash2 /></IconButton>}
    </span>
  </div>;
}

/* ── 产品规格书 ─────────────────────────────────────────────────── */

/** 规格书按顺序逐份添加：传了第一份，才会出现第二份的位置。 */
export function SpecSection<F extends AssetField>({ title, fields, env, onAdd, onReplace }: {
  title: string; fields: F[]; env: AssetEnv; onAdd: (files: File[]) => void; onReplace: (file: File, field: F) => void;
}) {
  const order = fields.map(f => f.name);
  const files = bySlot(env.assets, order);
  const editable = env.editable && !env.readOnly;
  const free = fields.length - files.length;
  const canAdd = editable && !env.unsaved && !env.busy && free > 0;
  if (!fields.length) return null;
  return <Frame title={title} meta={`${files.length} / ${fields.length} 份`}
    hint={editable ? `按顺序添加，最多 ${fields.length} 份。支持 PDF 或图片（JPG / PNG / WebP / GIF）。` : undefined}>
    {editable && env.unsaved && <Note>请先保存产品资料，之后才能上传规格书。</Note>}
    {!files.length && !editable && <p className="pa-empty">暂无规格书。</p>}
    {(files.length > 0 || editable) && <div className="pa-files">
      {files.map((a, i) => <FileRow key={a.id} asset={a} label={`规格书 ${i + 1}`} field={fields.find(f => f.name === a.field)} accept={SPEC_ACCEPT} env={env} onReplace={onReplace} />)}
      {editable && free > 0 && <DropCell variant="slim" enabled={canAdd} multiple={free > 1} accept={SPEC_ACCEPT}
        title={uploadTitle(env, files.length ? `添加规格书 ${files.length + 1}` : '上传产品规格书')} hint={env.unsaved || env.busy ? undefined : '拖入文件，或点击选择'} onFiles={onAdd} />}
    </div>}
  </Frame>;
}

/* ── 包装与标签 ─────────────────────────────────────────────────── */

function PackagingSlot<F extends AssetField>({ field, asset, env, onUpload }: {
  field: F; asset?: AssetItem; env: AssetEnv; onUpload: (files: File[], field: F) => void;
}) {
  const editable = env.editable && !env.readOnly;
  const enabled = editable && !env.unsaved && !env.busy;
  const zone = useDropZone(enabled, files => onUpload(files, field));
  const label = PACKAGING_LABELS[field.name] ?? field.name;
  return <div className={`pa-slot${zone.over ? ' is-over' : ''}`} {...zone.bind}>
    <span className="pa-slot-label" title={field.name}>{label}</span>
    {asset
      ? <FileRow asset={asset} field={field} env={env} onReplace={(file, f) => onUpload([file], f)} />
      : <DropCell variant="slim" dropOn={false} enabled={enabled} onFiles={files => onUpload(files, field)}
          title={uploadTitle(env, '拖入文件，或点击选择')} hint={env.unsaved || env.busy ? undefined : '图片、PDF、设计文件、压缩包均可'} />}
  </div>;
}

/** 每个位置各有名称（彩盒、外纸箱、标签文件……），所以固定列出；任何类型的文件都可以放。 */
export function PackagingSection<F extends AssetField>({ title, fields, env, onUpload }: {
  title: string; fields: F[]; env: AssetEnv; onUpload: (files: File[], field: F) => void;
}) {
  const editable = env.editable && !env.readOnly;
  const assetOf = (f: F) => env.assets.find(a => a.field === f.name);
  const shown = editable ? fields : fields.filter(f => assetOf(f));
  const filled = fields.filter(f => assetOf(f)).length;
  if (!fields.length) return null;
  return <Frame title={title} meta={`${filled} / ${fields.length} 个`}
    hint={editable ? '可拖入任何文件：图片、PDF、设计源文件（AI / PSD / CDR）或压缩包。每个位置放一个文件，多个文件请先打包成压缩包。' : undefined}>
    {editable && env.unsaved && <Note>请先保存产品资料，之后才能上传文件。</Note>}
    {!shown.length && <p className="pa-empty">暂无文件。</p>}
    {shown.length > 0 && <div className="pa-slots">
      {shown.map(f => <PackagingSlot key={f.name} field={f} asset={assetOf(f)} env={env} onUpload={onUpload} />)}
    </div>}
  </Frame>;
}
