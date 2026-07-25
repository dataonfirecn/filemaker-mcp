# 新建零件 WebViewer

独立入口：

```text
https://starrc.dataonfire.cn/?page=newPartWebViewer
```

该页面替代原生 FileMaker 的“新增零件资料”录入页。入口必须通过
`StarRC_WebViewerURL` 附加签名的 `ctx` / `sig`，页面不会接受匿名写入。

## FileMaker 布局与脚本

- 布局名：`Create New Part_Web`
- WebViewer 对象名：`wv_new_part`
- URL 计算：

```filemaker
StarRC_WebViewerURL ( "?page=newPartWebViewer" )
```

- 打开脚本：`新建零件_WebViewer`
- 创建成功回调脚本：`新建零件_WebViewer回调`
- 普通窗口中以 Card 窗口打开；已处于 Card 窗口时，以
  `1024 × 760` Dialog 窗口打开，避免嵌套 Card。
- 可粘贴脚本片段：
  `filemaker-clipboard-xml/08-open-new-part-webviewer-script-steps.fmxmlsnippet.xml`

## 页面内容

页面按照原生“新增零件资料”布局重新组织，包含：

- 零件编号、内部名称、对外名称、库存提醒
- 仓库分工、加工分类、统计分类、使用部门、量产状况、厂商编号
- 零件性质、部门分工、零件品种、材料性质、材质
- 仓库、位置 1、位置 2、重量、材料尺寸
- 专属客户、客户零件号
- 零件照片选择、预览、压缩与容器上传

内部名称和对外名称默认保持为空，只显示填写提示，不再预先写入提示文字。
邮件连结按钮暂不显示。

“生成零件编号”使用遮罩弹窗，并复用原独立编号 WebViewer 的性质、客户、
手工序号、加工、颜色、其他参数、组成预览和结果区。点击“生成”只在弹窗
内显示候选编号；只有点击“确认使用此编号”后，才写入新零件表单的零件
编号字段。编号弹窗会尽量使用 WebViewer 的可用高度；选项菜单使用加宽
面板并允许长名称换行，选中后立即关闭菜单。

“清空重来”必须在确认弹窗中再次确认后才执行。清空、检查和建立按钮固定
在 WebViewer 底部操作栏，不随表单内容浮动。

## FileMaker 数据来源

`GET /api/part-creation/options` 每次打开时从 FileMaker
`新增零件资料` 布局读取值列表：

- `倉庫分工`
- `零件性質`
- `加工分類`
- `零件狀態`
- `統計分類`
- `使用公司`
- `狀態`
- `零件品種`
- `材料分類`
- `倉庫`
- `零件材料尺寸`
- `客戶`

编号生成选项继续来自 `MaterialIDGenerator_Gen`。如果 FileMaker 暂时没有
返回仓库值列表，仓库字段会退回为手工输入，并在验证结果中提示。

## 验证与建立

- `POST /api/part-creation/validate` 只验证，不写入记录。
- `POST /api/part-creation/create` 再次读取实时选项、检查重复编号，然后通过
  Data API 在 `@零件` 建立记录。
- 必填：零件编号、正确的内部名称、正确的对外名称、仓库分工、零件性质。
- 验证内容包含编号字符、重复编号、值列表过期、客户代码与名称一致性、重量
  数值和照片格式/大小。
- 清空表单前要求二次确认；编号生成结果在用户确认前不会写回零件编号。
- 建立接口由 `FILEMAKER_PART_CREATE_ENABLED` 单独控制；不需要打开通用
  Data API 写入权限。
- 照片支持 JPG、PNG、WebP。浏览器先压缩，后端限制原始解码数据不超过
  `8 MB`，建立记录后上传到 FileMaker 容器字段。
- 如果照片上传失败，后端会删除刚建立的记录，避免留下没有照片的半成品。
- 建立成功后页面显示 FileMaker Record ID，并调用
  `新建零件_WebViewer回调`。回调保存本次创建结果后关闭 WebViewer。

## 创建成功回调

网页把后端返回的完整 JSON 作为脚本参数传给
`新建零件_WebViewer回调`。回调保存以下全局变量，便于 FileMaker
父窗口或后续脚本读取：

- `$$StarRC_NewPartResult`
- `$$StarRC_NewPartRecordId`
- `$$StarRC_NewPartPartNumber`
- `$$StarRC_NewPartPartId`
- `$$StarRC_NewPartPhotoUploaded`
- `$$StarRC_NewPartCallbackAt`

可粘贴回调步骤：
`filemaker-clipboard-xml/09-new-part-webviewer-callback-script-steps.fmxmlsnippet.xml`。

## 验收

- 所有页面选项均由 FileMaker 实时提供。
- 已验证编号生成、重复检查、必填/占位名称错误、仓库分工缺失、照片预处理
  和成功返回结构。
- 浏览器验收时没有点击“建立零件”，因此未在正式数据库写入测试记录。
