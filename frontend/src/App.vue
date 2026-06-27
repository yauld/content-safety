<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <main class="page">
        <header class="topbar">
          <div>
            <h1>内容安全审核台</h1>
            <p>{{ pageSubtitle }}</p>
            <small v-if="lastRefreshedAt">最后刷新：{{ formatTime(lastRefreshedAt) }}</small>
          </div>
          <div class="top-actions">
            <div class="view-tabs">
              <button :class="{ active: activeView === 'workbench' }" @click="switchView('workbench')">
                审核工作台
              </button>
              <button :class="{ active: activeView === 'records' }" @click="switchView('records')">
                处理记录
              </button>
              <button :class="{ active: activeView === 'dashboard' }" @click="switchView('dashboard')">
                数据看板
              </button>
            </div>
            <n-button class="top-action-button" secondary @click="submitDrawerVisible = true">提交测试</n-button>
            <n-button class="top-action-button" type="primary" :loading="refreshing" @click="refreshCurrentView">
              {{ refreshButtonText }}
            </n-button>
          </div>
        </header>

        <section v-if="activeView === 'workbench'" class="stats-grid">
          <div class="stat-card">
            <span>待审总数</span>
            <strong>{{ summary.pending_total }}</strong>
          </div>
          <div class="stat-card">
            <span>最长等待</span>
            <strong>{{ formatDuration(summary.pending_max_wait_seconds) }}</strong>
          </div>
          <div class="stat-card">
            <span>Agent 转人工</span>
            <strong>{{ summary.pending_agent }}</strong>
          </div>
          <div class="stat-card">
            <span>今日已处理</span>
            <strong>{{ summary.completed_today }}</strong>
          </div>
        </section>

        <section v-if="activeView === 'workbench'" class="workbench">
          <div class="panel queue-panel">
            <div class="panel-head">
              <div>
                <h2>待人工审核</h2>
                <p>优先处理高风险和 Agent 转人工内容。</p>
              </div>
              <span>{{ filteredPending.length }} / {{ pending.length }} 项</span>
            </div>

            <div class="filters">
              <n-input v-model:value="searchQuery" placeholder="搜索内容、原因、ID" clearable />
              <select v-model="riskFilter" class="filter-select">
                <option value="all">全部风险</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>

            <n-empty v-if="filteredPending.length === 0" description="暂无匹配的待审内容" />
            <div v-else class="queue-list">
              <button
                v-for="item in filteredPending"
                :key="item.thread_id"
                class="review-item"
                :class="{ active: selected?.thread_id === item.thread_id }"
                @click="selected = item"
              >
                <div class="review-meta">
                  <strong>{{ item.risk_level.toUpperCase() }}</strong>
                  <n-tag size="small" :type="stageTagType(resolveStage(item))">
                    {{ stageLabel(resolveStage(item), item.status) }}
                  </n-tag>
                </div>
                <div class="item-time">
                  <small>提交 {{ formatTime(item.created_at) }}</small>
                  <small>等待 {{ waitingDuration(item.created_at) }}</small>
                </div>
                <span>{{ item.reason }}</span>
                <small>{{ item.content }}</small>
              </button>
            </div>
          </div>

          <div class="panel detail-panel">
            <h2>审核详情</h2>
            <n-empty v-if="!selected" description="请选择一条待审内容" />
            <template v-else>
              <div class="detail-scroll">
                <div class="detail-section compact-section">
                  <label>原文</label>
                  <p class="content-box">{{ selected.content }}</p>
                </div>

                <div class="detail-grid">
                  <div>
                    <label>判断阶段</label>
                    <div class="tags">
                      <n-tag :type="stageTagType(resolveStage(selected))">
                        {{ stageLabel(resolveStage(selected), selected.status) }}
                      </n-tag>
                    </div>
                  </div>
                  <div>
                    <label>等待时长</label>
                    <p class="time-text">{{ waitingDuration(selected.created_at) }}</p>
                  </div>
                  <div>
                    <label>提交时间</label>
                    <p class="time-text">{{ formatDateTime(selected.created_at) }}</p>
                  </div>
                  <div>
                    <label>更新时间</label>
                    <p class="time-text">{{ formatDateTime(selected.updated_at) }}</p>
                  </div>
                  <div class="detail-grid-wide">
                    <label>规则命中</label>
                    <div class="tags">
                      <n-tag v-for="hit in selected.rule_hits" :key="hit" size="small">
                        {{ hit }}
                      </n-tag>
                      <span v-if="selected.rule_hits.length === 0">无</span>
                    </div>
                  </div>
                </div>

                <div class="detail-section evidence-section">
                  <label>证据</label>
                  <ul>
                    <li v-for="item in selected.evidence" :key="item">{{ item }}</li>
                    <li v-if="selected.evidence.length === 0">暂无</li>
                  </ul>
                </div>
              </div>

              <div class="review-form">
                <label>人工结论</label>
                <n-radio-group v-model:value="decision" class="decision-row">
                  <n-radio-button value="approved">通过</n-radio-button>
                  <n-radio-button value="rejected">拒绝</n-radio-button>
                  <n-radio-button value="needs_review">继续观察</n-radio-button>
                </n-radio-group>

                <label>常用原因</label>
                <div class="template-row">
                  <n-button
                    v-for="template in reasonTemplates"
                    :key="template.label"
                    size="small"
                    secondary
                    @click="applyReasonTemplate(template)"
                  >
                    {{ template.label }}
                  </n-button>
                </div>

                <label>人工原因</label>
                <n-input
                  v-model:value="reason"
                  class="review-reason"
                  type="textarea"
                  :autosize="{ minRows: 4, maxRows: 7 }"
                  placeholder="填写人工审核原因"
                />

                <div class="actions">
                  <n-button type="primary" :loading="resuming" @click="submitReview">
                    提交人工结论
                  </n-button>
                </div>
              </div>
            </template>
          </div>
        </section>

        <section v-else-if="activeView === 'records'" class="records-page panel">
          <div class="panel-head records-head">
            <div>
              <h2>处理记录</h2>
              <p>默认展示最近 50 条业务调用和人工处理结果。</p>
            </div>
            <span>{{ filteredRecords.length }} / {{ records.length }} 条</span>
          </div>

          <div class="records-filters">
            <n-input v-model:value="recordSearch" placeholder="搜索内容、原因、用户、场景、ID" clearable />
            <select v-model="recordDecisionFilter" class="filter-select">
              <option value="all">全部结论</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="needs_review">Needs Review</option>
            </select>
            <select v-model="recordStageFilter" class="filter-select">
              <option value="all">全部阶段</option>
              <option value="workflow">Workflow</option>
              <option value="agent">Agent</option>
              <option value="human">人工</option>
            </select>
            <select v-model="recordRiskFilter" class="filter-select">
              <option value="all">全部风险</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>

          <n-empty v-if="filteredRecords.length === 0" description="暂无匹配的处理记录" />
          <div v-else class="records-list">
            <article v-for="item in filteredRecords" :key="item.moderation_id" class="record-row">
              <div class="record-main">
                <div class="result-tags">
                  <n-tag size="small" :type="tagType(item.decision)">{{ item.decision }}</n-tag>
                  <n-tag size="small" :type="stageTagType(resolveStage(item))">
                    {{ stageLabel(resolveStage(item), item.status) }}
                  </n-tag>
                  <n-tag size="small">{{ item.risk_level.toUpperCase() }}</n-tag>
                </div>
                <h3>{{ item.reason }}</h3>
                <p>{{ item.content }}</p>
                <div class="record-meta">
                  <span>场景：{{ item.scene }}</span>
                  <span>用户：{{ item.user_id ?? '-' }}</span>
                  <span>处理：{{ formatDateTime(item.updated_at) }}</span>
                  <span>提交：{{ formatDateTime(item.created_at) }}</span>
                </div>
              </div>
              <div class="record-side">
                <span>{{ item.rule_hits.length ? item.rule_hits.join(', ') : '无规则命中' }}</span>
                <small>{{ item.moderation_id }}</small>
              </div>
            </article>
          </div>
        </section>

        <section v-else class="dashboard-page">
          <div class="dashboard-overview">
            <div class="analytics-card">
              <span>总提交量</span>
              <strong>{{ analytics.total_requests }}</strong>
              <small>已完成 {{ analytics.completed_total }}，待人工 {{ analytics.interrupted_total }}</small>
            </div>
            <div class="analytics-card">
              <span>自动完成率</span>
              <strong>{{ percentage(analytics.auto_completed_total, analytics.total_requests) }}</strong>
              <small>Workflow + Agent 自动完成</small>
            </div>
            <div class="analytics-card">
              <span>人工介入率</span>
              <strong>{{ percentage(analytics.human_involved_total, analytics.total_requests) }}</strong>
              <small>最长等待 {{ formatDuration(analytics.pending_max_wait_seconds) }}</small>
            </div>
            <div class="analytics-card">
              <span>今日处理</span>
              <strong>{{ analytics.completed_today }}</strong>
              <small>人工与自动完成合计</small>
            </div>
          </div>

          <div class="stage-grid">
            <div class="stage-card workflow-stage">
              <span>Workflow 规则初筛</span>
              <strong>{{ analytics.workflow.total }}</strong>
              <div>
                <small>通过 {{ analytics.workflow.approved }}</small>
                <small>拒绝 {{ analytics.workflow.rejected }}</small>
              </div>
            </div>
            <div class="stage-card agent-stage">
              <span>Agent 深度判断</span>
              <strong>{{ analytics.agent.total }}</strong>
              <div>
                <small>通过 {{ analytics.agent.approved }}</small>
                <small>拒绝 {{ analytics.agent.rejected }}</small>
                <small>转人工 {{ analytics.agent.needs_review }}</small>
              </div>
            </div>
            <div class="stage-card human-stage">
              <span>Human 人工审核</span>
              <strong>{{ analytics.human.total }}</strong>
              <div>
                <small>通过 {{ analytics.human.approved }}</small>
                <small>拒绝 {{ analytics.human.rejected }}</small>
                <small>继续观察 {{ analytics.human.needs_review }}</small>
              </div>
            </div>
          </div>

          <div class="chart-grid">
            <div class="panel chart-panel chart-wide">
              <div class="chart-head">
                <h2>审核链路漏斗</h2>
                <p>所有提交都会先进入 Workflow 规则初筛，再按需进入 Agent 复判和 Human 人工。</p>
              </div>
              <v-chart class="chart" :option="funnelOption" autoresize />
              <div class="funnel-note">
                <span>总量校验</span>
                <strong>
                  {{ humanReviewTotal }} + ({{ agentReviewTotal }} - {{ humanReviewTotal }}) +
                  ({{ analytics.total_requests }} - {{ agentReviewTotal }}) = {{ analytics.total_requests }}
                </strong>
                <small>Human 介入量 + Agent 自动完成量 + Workflow 直接完成量</small>
              </div>
            </div>
            <div class="panel chart-panel">
              <div class="chart-head">
                <h2>规则命中 Top</h2>
                <p>观察 Workflow 规则层的主要拦截来源。</p>
              </div>
              <v-chart class="chart" :option="ruleHitOption" autoresize />
            </div>
            <div class="panel chart-panel">
              <div class="chart-head">
                <h2>阶段分布</h2>
                <p>最终结论来源于 Workflow、Agent 或 Human。</p>
              </div>
              <v-chart class="chart" :option="stagePieOption" autoresize />
            </div>
            <div class="panel chart-panel">
              <div class="chart-head">
                <h2>风险分布</h2>
                <p>低、中、高风险内容的整体比例。</p>
              </div>
              <v-chart class="chart" :option="riskPieOption" autoresize />
            </div>
            <div class="panel chart-panel">
              <div class="chart-head">
                <h2>Agent 置信度</h2>
                <p>已产生置信度的 Agent 样本区间分布。</p>
              </div>
              <v-chart class="chart" :option="confidenceOption" autoresize />
            </div>
            <div class="panel chart-panel">
              <div class="chart-head">
                <h2>人工等待时长</h2>
                <p>当前待审队列的等待时间分布。</p>
              </div>
              <v-chart class="chart" :option="waitingOption" autoresize />
            </div>
          </div>
        </section>

        <n-drawer v-model:show="submitDrawerVisible" :width="560" placement="right">
          <n-drawer-content title="提交测试内容" closable>
            <div class="drawer-body">
              <n-input
                v-model:value="content"
                type="textarea"
                :autosize="{ minRows: 8, maxRows: 14 }"
                placeholder="输入一段需要审核的内容"
              />
              <div class="actions">
                <n-button type="primary" :loading="submitting" @click="submitContent">
                  提交审核
                </n-button>
              </div>

              <div v-if="lastResult" class="result">
                <h3>最近结果</h3>
                <div class="result-tags">
                  <n-tag :type="tagType(lastResult.decision)">
                    {{ lastResult.decision }}
                  </n-tag>
                  <n-tag :type="stageTagType(resolveStage(lastResult))">
                    {{ stageLabel(resolveStage(lastResult), lastResult.status) }}
                  </n-tag>
                </div>
                <p>{{ lastResult.reason }}</p>
                <small>thread_id: {{ lastResult.thread_id }}</small>
              </div>
            </div>
          </n-drawer-content>
        </n-drawer>
      </main>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { use } from 'echarts/core'
import { BarChart, FunnelChart, PieChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import {
  createDiscreteApi,
  darkTheme,
  NButton,
  NConfigProvider,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NMessageProvider,
  NRadioButton,
  NRadioGroup,
  NTag,
  type GlobalThemeOverrides,
} from 'naive-ui'
import {
  dashboardSummary,
  listPending,
  listRecent,
  moderate,
  resumeModeration,
  reviewSummary,
  type DashboardSummary,
  type Decision,
  type DecisionStage,
  type ModerateResponse,
  type ModerationRecord,
  type ReviewSummary,
} from './api'

use([
  BarChart,
  FunnelChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

type ActiveView = 'workbench' | 'records' | 'dashboard'

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#2dd4bf',
    primaryColorHover: '#5eead4',
    primaryColorPressed: '#14b8a6',
    bodyColor: '#0b1117',
    cardColor: '#111923',
    borderColor: '#253241',
    textColorBase: '#e5edf5',
  },
}

const { message } = createDiscreteApi(['message'])
const activeView = ref<ActiveView>('workbench')
const content = ref('这篇文章讨论暴力事件的新闻报道方式是否合适。')
const pending = ref<ModerationRecord[]>([])
const records = ref<ModerationRecord[]>([])
const summary = ref<ReviewSummary>({
  pending_total: 0,
  pending_max_wait_seconds: 0,
  pending_agent: 0,
  completed_today: 0,
})
const analytics = ref<DashboardSummary>({
  total_requests: 0,
  completed_total: 0,
  interrupted_total: 0,
  auto_completed_total: 0,
  human_involved_total: 0,
  workflow: { total: 0, approved: 0, rejected: 0, needs_review: 0 },
  agent: { total: 0, approved: 0, rejected: 0, needs_review: 0 },
  human: { total: 0, approved: 0, rejected: 0, needs_review: 0 },
  pending_total: 0,
  pending_max_wait_seconds: 0,
  completed_today: 0,
  rule_hits: {},
  risk_levels: {},
  decision_stages: {},
  confidence_buckets: {},
  waiting_buckets: {},
})
const selected = ref<ModerationRecord | null>(null)
const lastResult = ref<ModerateResponse | null>(null)
const submitting = ref(false)
const loadingPending = ref(false)
const loadingRecords = ref(false)
const loadingAnalytics = ref(false)
const resuming = ref(false)
const submitDrawerVisible = ref(false)
const lastRefreshedAt = ref<string | null>(null)
const decision = ref<Decision>('approved')
const reason = ref('人工判断为讨论或教育语境，可以通过。')
const searchQuery = ref('')
const riskFilter = ref<'all' | 'high' | 'medium' | 'low'>('all')
const recordSearch = ref('')
const recordDecisionFilter = ref<'all' | Decision>('all')
const recordStageFilter = ref<'all' | DecisionStage>('all')
const recordRiskFilter = ref<'all' | 'high' | 'medium' | 'low'>('all')

const reasonTemplates = [
  { label: '新闻/教育语境', decision: 'approved' as Decision, reason: '人工判断为新闻、讨论或教育语境，可以通过。' },
  { label: '明确违规', decision: 'rejected' as Decision, reason: '人工判断包含明确违规内容，需要拒绝。' },
  { label: '上下文不足', decision: 'needs_review' as Decision, reason: '上下文不足，继续观察并等待更多信息。' },
]

const selectedThreadId = computed(() => selected.value?.thread_id ?? '')
const refreshing = computed(() => loadingPending.value || loadingRecords.value || loadingAnalytics.value)

const pageSubtitle = computed(() => {
  if (activeView.value === 'workbench') return '聚焦待审队列，快速完成需要人工确认的审核项。'
  if (activeView.value === 'records') return '查看业务调用和人工处理结果，观察策略效果。'
  return '从 Workflow、Agent、Human 三层观察内容安全系统运行情况。'
})

const refreshButtonText = computed(() => {
  if (activeView.value === 'workbench') return '刷新待审'
  if (activeView.value === 'records') return '刷新记录'
  return '刷新看板'
})

const filteredPending = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  return pending.value.filter((item) => {
    const riskMatched = riskFilter.value === 'all' || item.risk_level === riskFilter.value
    const searchable = [
      item.content,
      item.reason,
      item.thread_id,
      item.moderation_id,
      item.user_id ?? '',
    ]
      .join(' ')
      .toLowerCase()
    return riskMatched && (!keyword || searchable.includes(keyword))
  })
})

const filteredRecords = computed(() => {
  const keyword = recordSearch.value.trim().toLowerCase()
  return records.value.filter((item) => {
    const stage = resolveStage(item)
    const decisionMatched = recordDecisionFilter.value === 'all' || item.decision === recordDecisionFilter.value
    const stageMatched = recordStageFilter.value === 'all' || stage === recordStageFilter.value
    const riskMatched = recordRiskFilter.value === 'all' || item.risk_level === recordRiskFilter.value
    const searchable = [
      item.content,
      item.reason,
      item.scene,
      item.thread_id,
      item.moderation_id,
      item.user_id ?? '',
      item.rule_hits.join(' '),
    ]
      .join(' ')
      .toLowerCase()
    return decisionMatched && stageMatched && riskMatched && (!keyword || searchable.includes(keyword))
  })
})

const chartTextColor = '#dbe6f3'
const chartSubtleColor = '#8fa1b5'
const chartGridColor = '#253241'
const chartPalette = ['#2dd4bf', '#60a5fa', '#f59e0b', '#a78bfa', '#f87171', '#34d399']

const agentAutoCompleted = computed(() => analytics.value.agent.approved + analytics.value.agent.rejected)
const agentReviewTotal = computed(() =>
  Math.max(0, analytics.value.total_requests - analytics.value.workflow.total),
)
const humanReviewTotal = computed(() => analytics.value.human.total + analytics.value.pending_total)
const funnelData = computed(() =>
  [
    { name: '进入 Workflow', value: analytics.value.total_requests },
    { name: '进入 Agent', value: agentReviewTotal.value },
    { name: '进入 Human', value: humanReviewTotal.value },
  ].filter((item) => item.value > 0 || item.name === '进入 Workflow'),
)

const funnelOption = computed(() => ({
  color: chartPalette,
  tooltip: {
    trigger: 'item',
    formatter: ({ name, value }: { name: string; value: number }) => {
      const notes: Record<string, string> = {
        '进入 Workflow': `所有提交都会先进入 Workflow 规则初筛，共 ${analytics.value.total_requests} 条`,
        '进入 Agent': `Workflow 未直接完成，进入 Agent 复判 ${agentReviewTotal.value} 条`,
        '进入 Human': `Agent 转人工总量 ${humanReviewTotal.value} 条，当前待人工 ${analytics.value.pending_total} 条`,
      }
      return `${name}: ${value}<br/>${notes[name] ?? ''}`
    },
  },
  series: [
    {
      type: 'funnel',
      left: '8%',
      top: 12,
      bottom: 8,
      width: '84%',
      minSize: '16%',
      sort: 'none',
      label: { color: chartTextColor, formatter: '{b}: {c}' },
      itemStyle: { borderColor: '#0b1117', borderWidth: 2 },
      data: funnelData.value,
    },
  ],
}))

const ruleHitOption = computed(() => barOption(topEntries(analytics.value.rule_hits, 8), '规则命中数'))
const confidenceOption = computed(() => barOption(orderedEntries(analytics.value.confidence_buckets), '样本数'))
const waitingOption = computed(() => barOption(orderedEntries(analytics.value.waiting_buckets), '待审数'))
const stagePieOption = computed(() => pieOption(labelEntries(analytics.value.decision_stages, stageName), '阶段分布'))
const riskPieOption = computed(() => pieOption(labelEntries(analytics.value.risk_levels, riskName), '风险分布'))

function barOption(entries: Array<[string, number]>, seriesName: string) {
  return {
    color: ['#2dd4bf'],
    tooltip: { trigger: 'axis' },
    grid: { left: 36, right: 12, top: 20, bottom: 42 },
    xAxis: {
      type: 'category',
      data: entries.map(([name]) => name),
      axisLabel: { color: chartSubtleColor, interval: 0, rotate: entries.length > 4 ? 24 : 0 },
      axisLine: { lineStyle: { color: chartGridColor } },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: chartSubtleColor },
      splitLine: { lineStyle: { color: chartGridColor } },
    },
    series: [{ name: seriesName, type: 'bar', data: entries.map(([, value]) => value), barMaxWidth: 30 }],
  }
}

function pieOption(entries: Array<[string, number]>, seriesName: string) {
  return {
    color: chartPalette,
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: chartSubtleColor } },
    series: [
      {
        name: seriesName,
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '42%'],
        label: { color: chartTextColor, formatter: '{b}: {c}' },
        data: entries.map(([name, value]) => ({ name, value })),
      },
    ],
  }
}

function topEntries(data: Record<string, number>, limit: number): Array<[string, number]> {
  return Object.entries(data)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
}

function orderedEntries(data: Record<string, number>): Array<[string, number]> {
  return Object.entries(data)
}

function labelEntries(
  data: Record<string, number>,
  labeler: (value: string) => string,
): Array<[string, number]> {
  return Object.entries(data).map(([key, value]) => [labeler(key), value])
}

function tagType(value: Decision) {
  if (value === 'approved') return 'success'
  if (value === 'rejected') return 'error'
  return 'warning'
}

type StageSource = Pick<ModerateResponse | ModerationRecord, 'decision_stage'>

function resolveStage(item: StageSource): DecisionStage {
  return item.decision_stage
}

function stageTagType(value: DecisionStage) {
  if (value === 'workflow') return 'info'
  if (value === 'agent') return 'warning'
  return 'success'
}

function toDate(value: string) {
  return new Date(value)
}

function formatDateTime(value: string) {
  const date = toDate(value)
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function formatTime(value: string) {
  const date = toDate(value)
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function formatDuration(seconds: number) {
  if (seconds < 60) return `${seconds}秒`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}分钟`
  const hours = Math.floor(minutes / 60)
  const restMinutes = minutes % 60
  if (hours < 24) return restMinutes > 0 ? `${hours}小时${restMinutes}分` : `${hours}小时`
  const days = Math.floor(hours / 24)
  const restHours = hours % 24
  return restHours > 0 ? `${days}天${restHours}小时` : `${days}天`
}

function waitingDuration(value: string) {
  const seconds = Math.max(0, Math.floor((Date.now() - toDate(value).getTime()) / 1000))
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const restMinutes = minutes % 60
  if (hours < 24) return restMinutes > 0 ? `${hours} 小时 ${restMinutes} 分钟` : `${hours} 小时`
  const days = Math.floor(hours / 24)
  const restHours = hours % 24
  return restHours > 0 ? `${days} 天 ${restHours} 小时` : `${days} 天`
}

function stageLabel(value: DecisionStage, status: 'completed' | 'interrupted') {
  if (status === 'interrupted') return 'Agent 转人工'
  if (value === 'workflow') return 'Workflow 判断'
  if (value === 'agent') return 'Agent 判断'
  return '人工判断'
}

function stageName(value: string) {
  if (value === 'workflow') return 'Workflow'
  if (value === 'agent') return 'Agent'
  if (value === 'human') return 'Human'
  return value
}

function riskName(value: string) {
  if (value === 'low') return '低风险'
  if (value === 'medium') return '中风险'
  if (value === 'high') return '高风险'
  return value
}

function percentage(value: number, total: number) {
  if (total <= 0) return '0%'
  return `${Math.round((value / total) * 100)}%`
}

async function submitContent() {
  if (!content.value.trim()) {
    message.warning('请先输入内容')
    return
  }
  submitting.value = true
  try {
    lastResult.value = await moderate(content.value)
    message.success(lastResult.value.status === 'interrupted' ? '已进入人工审核' : '审核完成')
    await Promise.all([loadDashboard(), loadAnalytics()])
    if (activeView.value === 'records') await loadRecords()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    submitting.value = false
  }
}

async function loadDashboard() {
  loadingPending.value = true
  try {
    const [pendingItems, summaryData] = await Promise.all([
      listPending(),
      reviewSummary(),
    ])
    pending.value = pendingItems
    summary.value = summaryData
    lastRefreshedAt.value = new Date().toISOString()
    if (selected.value) {
      selected.value = pending.value.find((item) => item.thread_id === selectedThreadId.value) ?? null
    }
    if (!selected.value && pending.value.length > 0) {
      selected.value = pending.value[0]
    }
  } catch (error) {
    message.error(error instanceof Error ? error.message : '加载失败')
  } finally {
    loadingPending.value = false
  }
}

async function loadRecords() {
  loadingRecords.value = true
  try {
    records.value = await listRecent(50)
    lastRefreshedAt.value = new Date().toISOString()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '加载处理记录失败')
  } finally {
    loadingRecords.value = false
  }
}

async function loadAnalytics() {
  loadingAnalytics.value = true
  try {
    analytics.value = await dashboardSummary()
    lastRefreshedAt.value = new Date().toISOString()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '加载数据看板失败')
  } finally {
    loadingAnalytics.value = false
  }
}

async function refreshCurrentView() {
  if (activeView.value === 'records') {
    await Promise.all([loadRecords(), loadDashboard()])
    return
  }
  if (activeView.value === 'dashboard') {
    await Promise.all([loadAnalytics(), loadDashboard()])
    return
  }
  await loadDashboard()
}

async function switchView(view: ActiveView) {
  activeView.value = view
  if (view === 'records' && records.value.length === 0) {
    await loadRecords()
  }
  if (view === 'dashboard') {
    await loadAnalytics()
  }
}

async function submitReview() {
  if (!selected.value) return
  if (!reason.value.trim()) {
    message.warning('请填写人工审核原因')
    return
  }
  resuming.value = true
  try {
    lastResult.value = await resumeModeration(selected.value.thread_id, decision.value, reason.value)
    message.success('人工结论已提交')
    selected.value = null
    await Promise.all([loadDashboard(), loadAnalytics()])
    if (activeView.value === 'records') await loadRecords()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '提交失败')
  } finally {
    resuming.value = false
  }
}

function applyReasonTemplate(template: (typeof reasonTemplates)[number]) {
  decision.value = template.decision
  reason.value = template.reason
}

onMounted(async () => {
  await loadDashboard()
  await loadAnalytics()
})
</script>
