import type { components, paths } from './generated/schema'

type CamelCase<Key extends string> = Key extends `${infer Head}_${infer Tail}`
  ? `${Head}${Capitalize<CamelCase<Tail>>}`
  : Key

export type Camelized<Value> = Value extends readonly (infer Item)[]
  ? Camelized<Item>[]
  : Value extends object
    ? {
        -readonly [Key in keyof Value as Key extends string ? CamelCase<Key> : Key]: Camelized<
          Value[Key]
        >
      }
    : Value

type Schemas = components['schemas']
type JsonBody<Response> = Response extends { content: { 'application/json': infer Body } }
  ? Body
  : never
type JsonRequestBody<Operation> = Operation extends {
  requestBody: { content: { 'application/json': infer Body } }
}
  ? Body
  : never

export type MeResponseDto = Camelized<JsonBody<paths['/api/v1/me']['get']['responses'][200]>>
export type MePatchDto = Camelized<Schemas['MePatch']>
export type TaskCreateDto = Camelized<Schemas['TaskCreate']>
export type TaskDetailDto = Camelized<
  JsonBody<paths['/api/v1/tasks/{task_id}']['get']['responses'][200]>
>
export type RunCreationDto = Camelized<JsonBody<paths['/api/v1/tasks']['post']['responses'][202]>>
export type ArticleContentUpdateDto = Camelized<Schemas['ArticleContentUpdate']>
export type ArticleUpdateResultDto = Camelized<
  JsonBody<paths['/api/v1/articles/{article_id}/content']['put']['responses'][200]>
>
export type ArticleRestoreDto = Camelized<
  JsonRequestBody<paths['/api/v1/articles/{article_id}/versions/restore']['post']>
>
export type ArticleRestoreResultDto = Camelized<
  JsonBody<paths['/api/v1/articles/{article_id}/versions/restore']['post']['responses'][200]>
>
export type ArticleRevisionCreateDto = Camelized<Schemas['ArticleRevisionCreate']>
export type ArticleRevisionResourceDto = Camelized<Schemas['ArticleRevisionResource']>
export type CurrentWechatOperationDto = Camelized<Schemas['CurrentWechatOperationResponse']>
export type UploadCreateResponseDto = Camelized<Schemas['UploadCreateResponse']>
export type UploadCreateDto = Camelized<Schemas['UploadCreate']>
export type UploadCompleteDto = Camelized<Schemas['UploadComplete']>
export type UploadCompleteResponseDto = Camelized<Schemas['UploadCompleteResponse']>
export type LayoutTemplateCreateDto = Camelized<Schemas['LayoutTemplateCreate']>
export type LayoutTemplatePatchDto = Camelized<Schemas['LayoutTemplatePatch']>

// Compile-time sentinels: these fail when a required user operation disappears or changes method.
export type RequiredUserOperations = {
  me: paths['/api/v1/me']['get']
  createTask: paths['/api/v1/tasks']['post']
  sendMessage: paths['/api/v1/tasks/{task_id}/messages']['post']
  streamRun: paths['/api/v1/ai-runs/{run_id}/events']['get']
  updateArticle: paths['/api/v1/articles/{article_id}/content']['put']
  currentWechatOperation: paths['/api/v1/articles/{article_id}/wechat-operation']['get']
  listLibrary: paths['/api/v1/library-items']['get']
  listAccounts: paths['/api/v1/official-accounts']['get']
}
