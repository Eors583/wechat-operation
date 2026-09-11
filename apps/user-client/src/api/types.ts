import type { components } from './generated/schema'

type BackendSchemas = components['schemas']

export type ThemePreference = BackendSchemas['MePatch']['theme_preference']
export type RunStage =
  | 'submitting'
  | 'queued'
  | 'validating'
  | 'clarifying'
  | 'reading'
  | 'planning'
  | 'generating'
  | 'checking'
  | 'saving'
  | 'ready'
  | 'reconnecting'
  | 'completed'
  | 'failed'
  | 'cancelled'
export type ArticleStatus = BackendSchemas['ArticleResource']['status']
export type LibraryItemType = 'article' | 'reference'
export type FileReadStatus = 'reading' | 'ready' | 'failed'
export type AccountStatus = 'connected' | 'reconnect' | 'unsupported'
export type TemplateStatus = 'idle' | 'extracting' | 'ready' | 'failed'
export type SkillScope = 'official' | 'personal'
export type ModuleKey = keyof BackendSchemas['StyleTokenPayload']

export interface User {
  id: string
  name: string
  role: string
  phone: string
  email: string
  points: number
  themePreference: ThemePreference
}

export interface Session {
  user: User
  accessToken: string
  refreshToken?: string
}

export interface VerificationChallenge {
  challengeId: string
  expiresAt: string
  deliveryStatus: string
  providerMode: 'configured'
  debugCode?: string
}

export interface PublicSettings {
  home: { welcomeMessage: string; examplePrompts: string[] }
  files: { allowedExtensions: string[]; maxFileMb: number; linkFetchEnabled: boolean }
  ai: {
    maxClarificationRounds: number
    minArticleLength: number
    maxArticleLength: number
    preferenceEnabledByDefault: boolean
  }
  articles: { autosaveSeconds: number; historyVersions: number }
  wechat: { wechatDraftEnabled: boolean; wechatPublishEnabled: boolean; maxArticleImages: number }
  features: { featureFlags: Record<string, boolean> }
}

export const createDefaultPublicSettings = (): PublicSettings => ({
  home: {
    welcomeMessage: '今天想创作什么？',
    examplePrompts: [
      '根据这份资料写一篇公众号文章',
      '把这篇旧文章重新改写',
      '围绕这个主题先给我几个选题',
    ],
  },
  files: {
    allowedExtensions: [
      'pdf',
      'docx',
      'pptx',
      'xlsx',
      'csv',
      'txt',
      'md',
      'html',
      'png',
      'jpg',
      'jpeg',
      'mp3',
      'm4a',
      'mp4',
    ],
    maxFileMb: 200,
    linkFetchEnabled: true,
  },
  ai: {
    maxClarificationRounds: 2,
    minArticleLength: 300,
    maxArticleLength: 12000,
    preferenceEnabledByDefault: true,
  },
  articles: { autosaveSeconds: 20, historyVersions: 50 },
  wechat: { wechatDraftEnabled: true, wechatPublishEnabled: true, maxArticleImages: 30 },
  features: {
    featureFlags: {
      personal_skills: true,
      template_extraction: true,
      external_knowledge: false,
      visual_understanding: true,
    },
  },
})

export interface AccountDeletionReceipt {
  deletionRequestId: string
  status: 'scheduled'
  requestedAt: string
  purgeAfter: string
}

export interface Project {
  id: string
  name: string
  description: string
  writingRequirements: string
  updatedAt: string
}

export interface Attachment {
  id: string
  name: string
  kind: 'file' | 'image' | 'link'
  size?: number
  mimeType?: string
  url?: string
  status: FileReadStatus
  saveToLibrary: boolean
  assetId?: string
  documentId?: string
  /** Browser/native file handle. Never serialized into an API request. */
  sourceFile?: File
}

export interface Task {
  id: string
  title: string
  projectId: string | null
  currentArticleId: string | null
  currentSkillId: string | null
  usePreferences: boolean
  updatedAt: string
  status: 'active' | 'archived'
}

export interface Message {
  id: string
  clientMessageId?: string
  taskId: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  attachments?: Attachment[]
  skillIds?: string[]
  articleId?: string
  articleVersionNo?: number
  titleCandidates?: string[]
  titleArticleId?: string
  suggestions?: string[]
  responseKind?: string
  aiRunId?: string
  errorCode?: string
  retryable?: boolean
  sourceMessageId?: string
  preferenceReview?: string
  preferenceReviewRequestedAt?: string
  preferenceProposal?: {
    value: string
    previousValue?: string
    status: string
    expiresAt: string
  }
}

export interface TaskAIRunSummary {
  id: string
  status: BackendSchemas['TaskAIRunSummary']['status']
  runType: string
  errorCode?: string
  errorMessage?: string
  createdAt: string
  completedAt?: string
}

export interface Article {
  id: string
  title: string
  summary: string
  taskId: string
  projectId: string | null
  status: ArticleStatus
  updatedAt: string
  versionNo: number
  contentHtml: string
  contentJson?: Record<string, unknown>
  coverState: 'missing' | 'ready'
  renderId: string | null
  accountId: string | null
  templateId: string | null
  publishedUrl?: string
  lastOperationStatus?: 'succeeded'
}

export interface ArticleVersion {
  id: string
  articleId: string
  versionNo: number
  reason: string
  createdAt: string
  contentHtml: string
  contentJson?: Record<string, unknown>
  title: string
}

export interface LibraryItem {
  sourceTaskTitle?: string
  id: string
  type: LibraryItemType
  title: string
  projectId: string | null
  taskId: string | null
  status: ArticleStatus | FileReadStatus
  updatedAt: string
  summary: string
  fileType?: string
  size?: number
  sourceId: string
  previewPages?: string[]
  extractedText?: string
  pageCount?: number
  parserVersion?: string
}

export interface Skill {
  id: string
  scope: SkillScope
  name: string
  description: string
  category: string
  enabled: boolean
  scenes: string
  requirements: string
  examples: string[]
}

export interface ModuleStyle {
  borderAll?: string
  enabled?: boolean
  fontSize: number
  fontWeight: '400' | '500' | '600' | '700'
  color: string
  background: string
  align: 'left' | 'center' | 'right' | 'justify'
  lineHeight: number
  spacing: number
  marginTop?: number
  textIndent?: number
  padding: number
  border: 'none' | 'left'
  borderLeft?: string
}

export interface LayoutTemplate {
  id: string
  accountId: string | null
  name: string
  enabled: boolean
  sourceUrl: string
  status: TemplateStatus
  updatedAt: string
  sourcePreview: string[]
  extractionMode: 'agent' | 'deterministic_fallback' | 'manual'
  styles: Record<ModuleKey, ModuleStyle>
}

export interface OfficialAccount {
  id: string
  name: string
  avatarText: string
  avatarColor: string
  status: AccountStatus
  authorizedAt: string
  lastSyncedAt: string
  capabilities: string[]
}

export interface OfficialAccountAuthorization {
  authorizationUrl: string
  expiresIn: number
}

export interface Preference {
  id: string
  title: string
  text: string
  source: string
  status: 'candidate' | 'confirmed'
  updatedAt: string
}

export interface ModelOption {
  id: string
  name: string
  providerName: string
  modelId: string
  modelType: 'chat' | 'vision'
  contextWindow: number
  maxOutputTokens: number
}

export interface TaskBundle {
  task: Task
  messages: Message[]
  messagesNextCursor?: string
  latestAiRun: TaskAIRunSummary | null
  article: Article | null
}

export interface MessagePage {
  items: Message[]
  nextCursor?: string
}

export interface CursorPage<T> {
  items: T[]
  nextCursor?: string
}

export type ProjectPage = CursorPage<Project>
export type TaskPage = CursorPage<Task>
export type ArticleVersionPage = CursorPage<ArticleVersion>
export type SkillPage = CursorPage<Skill>
export type OfficialAccountPage = CursorPage<OfficialAccount>
export type LayoutTemplatePage = CursorPage<LayoutTemplate>
export type PreferencePage = CursorPage<Preference>

export interface AttachmentUploadProgress {
  id: string
  name: string
  loaded: number
  total: number
  phase: 'uploading' | 'processing' | 'ready'
}

export interface SendMessageInput {
  retryOfRunId?: string
  clientMessageId?: string
  taskId?: string
  projectId?: string | null
  text: string
  skillId?: string | null
  skillIds?: string[]
  modelDeploymentId?: string | null
  usePreferences: boolean
  attachments: Attachment[]
  signal?: AbortSignal
  onRunAccepted?: (runId: string, taskId: string, clientMessageId?: string) => void | Promise<void>
  onRunStage?: (stage: RunStage) => void
  onTextDelta?: (text: string) => void
  onArticleReady?: (articleId: string) => void
  onWarning?: (message: string) => void
  onAttachmentUploaded?: (attachment: Attachment) => void
  onAttachmentProgress?: (progress: AttachmentUploadProgress) => void
}

export interface SendMessageResult extends TaskBundle {
  runId: string
}

export interface ArticleSaveInput {
  id: string
  title: string
  contentHtml: string
  contentJson?: Record<string, unknown>
  summary?: string
  baseVersionNo: number
  reason?: string
}

export interface ArticleOutcomeInput {
  id: string
  outcome: 'local_draft' | 'wechat_draft' | 'publish'
  accountId?: string
  templateId?: string
  renderId?: string
  idempotencyKey: string
}

export interface ArticleRenderPreview {
  renderId: string
  html: string
}

export interface ArticleRevisionInput {
  articleId: string
  baseVersionNo: number
  selectedText: string
  instruction: string
  selectionFrom: number
  selectionTo: number
}

export interface ArticleRevisionProposal {
  id: string
  replacementText: string
}

export interface PendingArticleRevision extends ArticleRevisionInput {
  ownerId: string
  idempotencyKey: string
  revisionId?: string
  createdAt: string
}

export interface PendingArticleOutcome {
  ownerId: string
  articleId: string
  outcome: 'wechat_draft' | 'publish'
  accountId: string
  templateId: string
  renderId: string
  idempotencyKey: string
  operationId?: string
  operationStatus: 'queued' | 'submitting' | 'reconciling' | 'unknown'
  createdAt: string
}

export interface LibraryFilters {
  type?: LibraryItemType | 'all'
  projectId?: string | 'all' | 'unclassified'
  search?: string
}

export interface LibraryPage {
  items: LibraryItem[]
  nextCursor?: string
}

export interface SkillInput {
  id?: string
  name: string
  scenes: string
  requirements: string
  examples: string[]
}

export interface UserApi {
  login(identifier: string, password: string): Promise<Session>
  loginWithCode(identifier: string, challengeId: string, code: string): Promise<Session>
  requestVerificationCode(
    destination: string,
    purpose: 'register' | 'login' | 'reset_password',
  ): Promise<VerificationChallenge>
  register(phone: string, challengeId: string, code: string, password: string): Promise<Session>
  logout(): Promise<void>
  deleteAccount(password: string, confirmation: '注销账号'): Promise<AccountDeletionReceipt>
  getMe(): Promise<User>
  getPublicSettings(): Promise<PublicSettings>
  listProjectsPage(cursor?: string, limit?: number): Promise<ProjectPage>
  createProject(name: string): Promise<Project>
  updateProject(
    id: string,
    patch: Partial<Pick<Project, 'name' | 'description' | 'writingRequirements'>>,
  ): Promise<Project>
  deleteProject(id: string): Promise<void>
  listTasksPage(projectId?: string | null, cursor?: string, limit?: number): Promise<TaskPage>
  getTask(id: string): Promise<TaskBundle>
  listTaskMessages(id: string, cursor: string, limit?: number): Promise<MessagePage>
  decidePreference(
    taskId: string,
    messageId: string,
    decision: 'confirmed' | 'dismissed',
  ): Promise<void>
  uploadFile(
    file: File,
    context?: {
      projectId?: string | null
      taskId?: string | null
      saveToLibrary?: boolean
      waitForReady?: boolean
      signal?: AbortSignal
    },
  ): Promise<Attachment>
  sendMessage(input: SendMessageInput): Promise<SendMessageResult>
  hasPendingMessage(): boolean
  getPendingMessage(taskId: string): { key: string; message: Message } | null
  resumePendingMessage(
    input?: Pick<
      SendMessageInput,
      'signal' | 'onRunAccepted' | 'onRunStage' | 'onTextDelta' | 'onArticleReady' | 'onWarning'
    > & { pendingKey?: string },
  ): Promise<SendMessageResult | null>
  cancelRun(id: string): Promise<void>
  updateTask(id: string, patch: Partial<Pick<Task, 'title' | 'projectId'>>): Promise<Task>
  deleteTask(id: string): Promise<void>
  getArticle(id: string): Promise<Article>
  saveArticle(input: ArticleSaveInput): Promise<Article>
  getArticleVersionsPage(id: string, cursor?: string, limit?: number): Promise<ArticleVersionPage>
  restoreArticleVersion(
    articleId: string,
    version: Pick<ArticleVersion, 'id' | 'versionNo'>,
  ): Promise<Article>
  proposeArticleRevision(input: ArticleRevisionInput): Promise<ArticleRevisionProposal>
  getPendingArticleRevision(articleId: string): PendingArticleRevision | null
  resumePendingArticleRevision(articleId: string): Promise<ArticleRevisionProposal | null>
  prepareArticleRender(
    articleId: string,
    accountId: string | null,
    templateId: string | null,
    coverAssetId?: string | null,
    articleVersionNo?: number,
  ): Promise<ArticleRenderPreview>
  downloadArticleRender(renderId: string, format: 'md' | 'pdf' | 'docx'): Promise<Blob>
  setArticleOutcome(input: ArticleOutcomeInput): Promise<Article>
  getPendingArticleOutcome(articleId: string): PendingArticleOutcome | null
  refreshPendingArticleOutcome(articleId: string): Promise<PendingArticleOutcome | null>
  resumePendingArticleOutcome(articleId: string): Promise<Article | null>
  listLibraryItemsPage(
    filters?: LibraryFilters,
    cursor?: string,
    limit?: number,
  ): Promise<LibraryPage>
  getLibraryItem(id: string): Promise<LibraryItem>
  downloadDocument(id: string): Promise<Blob>
  updateLibraryItemTitle(id: string, title: string): Promise<LibraryItem>
  deleteLibraryItem(id: string): Promise<void>
  reparseDocument(id: string): Promise<void>
  listSkillsPage(cursor?: string, limit?: number, query?: string): Promise<SkillPage>
  getSkill(id: string): Promise<Skill>
  saveSkill(input: SkillInput): Promise<Skill>
  setSkillEnabled(id: string, enabled: boolean): Promise<Skill>
  deleteSkill(id: string): Promise<void>
  listOfficialAccountsPage(cursor?: string, limit?: number): Promise<OfficialAccountPage>
  getOfficialAccount(id: string): Promise<OfficialAccount>
  createOfficialAccountAuthorization(redirectUri: string): Promise<OfficialAccountAuthorization>
  completeOfficialAccountAuthorization(
    accountId?: string,
    previousAccountIds?: string[],
  ): Promise<OfficialAccount | null>
  disconnectOfficialAccount(id: string): Promise<void>
  listTemplatesPage(
    accountId?: string | null,
    cursor?: string,
    limit?: number,
  ): Promise<LayoutTemplatePage>
  extractTemplate(accountId: string | null | undefined, url: string): Promise<LayoutTemplate>
  saveTemplate(template: LayoutTemplate): Promise<LayoutTemplate>
  deleteTemplate(id: string): Promise<void>
  listPreferencesPage(cursor?: string, limit?: number): Promise<PreferencePage>
  savePreference(text: string, id?: string, status?: 'candidate' | 'confirmed'): Promise<Preference>
  confirmPreference(id: string): Promise<Preference>
  deletePreference(id: string): Promise<void>
  updateThemePreference(preference: ThemePreference): Promise<User>
  listModelOptions(): Promise<ModelOption[]>
}
