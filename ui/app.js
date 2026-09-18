/* =====================================================================
   SellPilot · 跨境选品与上架作战台
   结构：总览（01 选品 / 02 Listing）→ 模块控制台（左表单 + 右对话流）
   - 每个板块一条独立会话（session_id 存 localStorage）
   - 表单 → 结构化提问 → POST /api/ask → 卡片渲染（后端不可达时本地演示兜底）
   - 设置面板：API Key / 请求地址 / 模型 ID（POST /api/settings，可测试连接）
   ===================================================================== */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const now = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const DELAY = () => 700 + Math.random() * 500;

function escapeHTML(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- 多语言文案 ---------- */
const I18N = {
  zh: {
    docTitle: "SellPilot · 跨境选品与上架工作台",
    brandSub: "跨境选品 · 上架工作台",
    crumbHome: "总览", back: "返回总览",
    settings: "设置", debug: "调试后台",
    heroKicker: "OPERATIONS · SELECT → LIST",
    heroTitle: "两条产线，一次跑通",
    heroLead: "选品解决「卖什么」，Listing 解决「怎么卖」。挑一个模块进入，或在模块里直接自由对话。",
    boardResearch: "选品", boardResearchDesc: "需求 · 竞争 · 利润 · 货源，四步筛出能赚钱的品。",
    boardListing: "Listing", boardListingDesc: "文案 · 图片 · 定价 · 履约，把品推上货架。",
    placeholder: "直接说需求…（Enter 发送 / Shift+Enter 换行）",
    hint: "AI 多智能体 · 选品 + 上架",
    thinking: "智能体思考中…", replied: "已回复",
    runModule: "开始分析", required: "请先填写：",
    freeTip: "这个模块不预设表单 —— 直接在右下角输入框里描述你的需求即可。",
    you: "你", agent: "SELPILOT",
    endTalk: "结束谈话", clear: "清空",
    endDone: "本次谈话已结束并完成 <span class='em'>总结归档</span>（多轮记忆与长期画像已更新）。已开启新一轮谈话～",
    endFail: "结束谈话未成功（后端不可达），请稍后重试。",
    cleared: "已清空当前板块的对话。",
    switched: "已切换为中文。",
    greet: "这里是<b>{name}</b>模块。左侧填好参数点「开始分析」，或直接在下方输入框里说需求。",
    settingsTitle: "运行时配置",
    setKey: "API Key", setUrl: "请求地址（Base URL）", setModel: "模型 ID",
    setTemp: "温度 temperature", setPerm: "权限模式",
    permPlan: "plan · 只读", permAsk: "ask · 写操作需确认",
    permAccept: "accept · 低风险自动放行", permBypass: "bypass · 完全放开",
    setCallBudget: "单次 token 预算", setCost: "累计金额上限（单会话）",
    setCostNote: r => `0 = 不启用金额熔断。USD 按 1 USD ≈ ${r} CNY 折算成人民币与账单对齐。`,
    setPersist: "写入本机 .env（重启后仍生效）", setTest: "测试连接", setSave: "保存并应用",
    setKeyNone: "当前未配置密钥（本地演示模式）",
    setKeyMasked: k => `当前已配置：${k}（留空则保持不变）`,
    keyOk: " · 连接测试已通过", keyBad: " · 上次连接测试失败", keyUnverified: " · 尚未验证",
    saveNone: "没有需要更新的内容。",
    saveOk: (n, p) => `已更新 ${n} 项${p ? "，并写入本机 .env" : "（仅本次运行有效）"}。`,
    saveFail: "保存失败：",
    testing: "正在测试连接…",
    testOk: m => `连接成功 · 模型 ${m}`,
    testFail: "连接失败：",
    statusLive: m => `GLM 在线 · ${m}`,
    statusLocal: "本地演示模式", statusDown: "后端未连接",
    statusUnverified: "GLM 已配置 · 待验证", statusKeyBad: "密钥校验失败",
    card: {
      verdict: "选品结论", score: "四步得分", passed: "通过", failed: "未通过",
      supplier: "供应商对比", recommend: "综合推荐", moq: "起订量", unitPrice: "单价", lead: "交期",
      draft: "Listing 草稿", bullets: "五点描述", terms: "Search Terms", tips: "合规提示",
      images: "图片合规自检", price: "定价建议", suggested: "建议售价", floor: "保本底价",
      fulfill: "履约建议", mode: "建议方式", batch: "首批备货",
      order: "订单", carrier: "顺丰速运", reco: "智能推荐 · 商品库命中",
      steps: ["已付款", "运输中", "派送中", "已签收"], paidAt: "昨天 15:02 付款"
    }
  },
  ja: {
    docTitle: "SellPilot · 越境セラー選品・出品コンソール",
    brandSub: "選品・出品コンソール",
    crumbHome: "全体", back: "全体へ戻る",
    settings: "設定", debug: "デバッグ",
    heroKicker: "OPERATIONS · SELECT → LIST",
    heroTitle: "2本のラインを、一度に",
    heroLead: "選品は「何を売るか」、Listing は「どう売るか」。モジュールを選ぶか、そのまま自由に相談してください。",
    boardResearch: "選品", boardResearchDesc: "需要・競合・利益・仕入れ先。4ステップで利益の出る商品を絞り込み。",
    boardListing: "Listing", boardListingDesc: "コピー・画像・価格・フルフィルメント。商品を棚に上げる。",
    placeholder: "ご要望を入力…（Enterで送信 / Shift+Enterで改行）",
    hint: "AI マルチエージェント · 選品 + 出品",
    thinking: "エージェントが考え中…", replied: "返信しました",
    runModule: "分析を開始", required: "未入力です：",
    freeTip: "このモジュールに固定フォームはありません。右下の入力欄から直接ご要望をどうぞ。",
    you: "あなた", agent: "SELPILOT",
    endTalk: "会話を終了", clear: "消去",
    endDone: "今回の会話は終了し、<span class='em'>要約を保存</span>しました（多輪記憶と長期プロファイルを更新済み）。新しい会話を開始しました〜",
    endFail: "会話の終了に失敗しました（バックエンド未接続）。後ほどお試しください。",
    cleared: "このワークベンチの会話を消去しました。",
    switched: "日本語に切り替えました。",
    greet: "こちらは<b>{name}</b>モジュールです。左のフォームで実行するか、下の入力欄から直接どうぞ。",
    settingsTitle: "ランタイム設定",
    setKey: "API Key", setUrl: "リクエスト先（Base URL）", setModel: "モデル ID",
    setTemp: "温度 temperature", setPerm: "権限モード",
    permPlan: "plan · 読み取り専用", permAsk: "ask · 書き込みは要確認",
    permAccept: "accept · 低リスクは自動許可", permBypass: "bypass · 全開放",
    setCallBudget: "1回あたり token 予算", setCost: "累計金額上限（1セッション）",
    setCostNote: r => `0 = 金額ブレーキ無効。USD は 1 USD ≈ ${r} CNY で人民元換算し、請求と突き合わせます。`,
    setPersist: "ローカルの .env に保存（再起動後も有効）", setTest: "接続テスト", setSave: "保存して適用",
    setKeyNone: "キー未設定（ローカルデモモード）",
    setKeyMasked: k => `設定済み：${k}（空欄なら変更しません）`,
    keyOk: " · 接続テスト済み", keyBad: " · 前回の接続テストに失敗", keyUnverified: " · 未検証",
    saveNone: "更新する項目がありません。",
    saveOk: (n, p) => `${n} 件を更新しました${p ? "（.env に保存）" : "（今回の実行のみ有効）"}。`,
    saveFail: "保存に失敗：",
    testing: "接続をテスト中…",
    testOk: m => `接続成功 · モデル ${m}`,
    testFail: "接続失敗：",
    statusLive: m => `GLM オンライン · ${m}`,
    statusLocal: "ローカルデモモード", statusDown: "バックエンド未接続",
    statusUnverified: "GLM 設定済み · 未検証", statusKeyBad: "キー検証に失敗",
    card: {
      verdict: "選品結論", score: "4段階スコア", passed: "合格", failed: "不合格",
      supplier: "仕入れ先比較", recommend: "総合おすすめ", moq: "最小ロット", unitPrice: "単価", lead: "納期",
      draft: "Listing 下書き", bullets: "箇条書き", terms: "Search Terms", tips: "規約ヒント",
      images: "画像規約チェック", price: "価格提案", suggested: "推奨価格", floor: "損益分岐価格",
      fulfill: "フルフィルメント提案", mode: "推奨方式", batch: "初回仕入れ",
      order: "ご注文", carrier: "順豊エクスプレス", reco: "おすすめ · 商品ライブラリから",
      steps: ["支払い済み", "輸送中", "配達中", "受取済み"], paidAt: "昨日 15:02 支払い済み"
    }
  }
};

let lang = localStorage.getItem("sellpilot-lang") || "zh";
const L = () => I18N[lang];
const tr = obj => (obj && (obj[lang] ?? obj.zh)) || "";

/* ---------- 站点下拉（中/日共用） ---------- */
const SITES = [["US", "Amazon US"], ["JP", "Amazon JP"], ["DE", "Amazon DE"], ["GB", "Amazon UK"]];
const SITE_FIELD = { name: "site", label: { zh: "目标站点", ja: "対象サイト" }, type: "select", options: SITES };

/* ---------- 板块与模块定义 ---------- */
const BOARDS = {
  research: {
    no: "01", tag: "SELECT", sidKey: "sellpilot-sid-research", msgsId: "msgs-research",
    title: () => L().boardResearch,
    modules: [
      {
        no: "1.1", key: "demand",
        title: { zh: "需求验证", ja: "需要検証" },
        desc: { zh: "搜索量 / 价格带 / 重量门槛，先确认这个品有没有人买。", ja: "検索量・価格帯・重量。まず需要の有無を確認。" },
        fields: [
          { name: "category", label: { zh: "品类 / 关键词", ja: "カテゴリ / キーワード" }, ph: { zh: "例如：便携榨汁杯", ja: "例：ポータブルジューサー" }, required: true },
          SITE_FIELD,
          { name: "price", label: { zh: "目标售价（$）", ja: "目標価格（$）" }, type: "number", ph: { zh: "29.9", ja: "29.9" } }
        ],
        prompt: (v, zh) => zh
          ? `对「${v.category}」做需求验证：目标站点 ${v.site}，目标售价约 $${v.price || "未定"}。请检查搜索量是否达标、售价是否落在 $20~$70 区间、单品重量是否低于 2lb，并给出明确的需求结论。`
          : `「${v.category}」の需要検証をお願いします。対象 ${v.site}、目標価格 約$${v.price || "未定"}。検索ボリューム・価格帯（$20〜$70）・重量（2lb未満）を確認し、明確な結論を出してください。`
      },
      {
        no: "1.2", key: "competition",
        title: { zh: "竞争分析", ja: "競合分析" },
        desc: { zh: "首页竞品评分与评论数，判断进入难度。", ja: "上位の評価・レビュー数から参入難易度を判断。" },
        fields: [
          { name: "category", label: { zh: "品类 / 关键词", ja: "カテゴリ / キーワード" }, ph: { zh: "例如：蓝牙耳机", ja: "例：ワイヤレスイヤホン" }, required: true },
          SITE_FIELD
        ],
        prompt: (v, zh) => zh
          ? `分析「${v.category}」在 ${v.site} 的竞争强度：请给出首页竞品的平均评分、平均评论数、是否存在垄断卖家，并判断是否值得进入。`
          : `「${v.category}」(${v.site}) の競合強度を分析してください。上位の平均評価・平均レビュー数・独占セラーの有無を示し、参入すべきか判断してください。`
      },
      {
        no: "1.3", key: "profit",
        title: { zh: "利润测算", ja: "利益試算" },
        desc: { zh: "折算头程、佣金、FBA 与广告，算清算净利。", ja: "輸送・手数料・FBA・広告を織り込み純利益を算出。" },
        fields: [
          { name: "category", label: { zh: "品类 / 关键词", ja: "カテゴリ / キーワード" }, ph: { zh: "例如：云感耳机", ja: "例：雲感イヤホン" }, required: true },
          { name: "cost", label: { zh: "采购成本（¥）", ja: "仕入原価（¥）" }, type: "number", ph: { zh: "45", ja: "45" } },
          { name: "price", label: { zh: "目标售价（$）", ja: "目標価格（$）" }, type: "number", ph: { zh: "29.9", ja: "29.9" } }
        ],
        prompt: (v, zh) => zh
          ? `测算「${v.category}」的利润：采购成本约 ¥${v.cost || "未知"}，目标售价 $${v.price || "未知"}。请折算头程、平台佣金、FBA 配送费与广告费，给出单件利润与净利率，并判断是否达到 30% 净利率红线。`
          : `「${v.category}」の利益を試算してください。仕入原価 約¥${v.cost || "不明"}、目標価格 $${v.price || "不明"}。輸送費・手数料・FBA配送料・広告費を織り込み、1個あたり利益と純利益率を示し、純利益率30%のラインを満たすか判断してください。`
      },
      {
        no: "1.4", key: "supplier",
        title: { zh: "供应商对比", ja: "仕入れ先比較" },
        desc: { zh: "单价 / 起订量 / 交期 / 评分横向比。", ja: "単価・最小ロット・納期・評価を横断比較。" },
        fields: [
          { name: "keyword", label: { zh: "货源关键词", ja: "仕入れキーワード" }, ph: { zh: "例如：蓝牙耳机", ja: "例：ワイヤレスイヤホン" }, required: true },
          { name: "moq", label: { zh: "可接受起订量（件）", ja: "許容できる最小ロット（個）" }, type: "number", ph: { zh: "100", ja: "100" } }
        ],
        prompt: (v, zh) => zh
          ? `对比「${v.keyword}」的供应商货源，起订量希望控制在 ${v.moq || "不限"} 件以内。请给出候选货源的单价、起订量、交期与评分对比，并给出综合推荐与理由。`
          : `「${v.keyword}」の仕入れ先を比較してください。最小ロットは ${v.moq || "問わない"} 個以内が希望です。候補ごとに単価・最小ロット・納期・評価を比較し、総合おすすめと理由を示してください。`
      },
      {
        no: "1.5", key: "report",
        title: { zh: "一键选品报告", ja: "選品レポート一括" },
        desc: { zh: "需求 + 竞争 + 利润一次跑完，出推进/放弃结论。", ja: "需要・競合・利益を一括で検証し、結論を出す。" },
        fields: [
          { name: "category", label: { zh: "品类 / 关键词", ja: "カテゴリ / キーワード" }, ph: { zh: "例如：便携榨汁杯", ja: "例：ポータブルジューサー" }, required: true },
          SITE_FIELD
        ],
        prompt: (v, zh) => zh
          ? `对「${v.category}」（站点 ${v.site}）出具一份完整选品报告：依次完成需求验证、竞争分析、利润测算三步，给出总分以及「推进 / 放弃」的明确结论。`
          : `「${v.category}」(${v.site}) の選品レポートを作成してください。需要検証・競合分析・利益試算を順に実施し、総合スコアと「推進 / 見送り」の明確な結論を出してください。`
      },
      {
        no: "1.6", key: "free", free: true,
        title: { zh: "自由对话", ja: "フリートーク" },
        desc: { zh: "没有合适模块？直接描述你的选品问题。", ja: "該当モジュールがない場合は自由に相談。" },
        fields: []
      }
    ]
  },

  listing: {
    no: "02", tag: "LIST", sidKey: "sellpilot-sid-listing", msgsId: "msgs-listing",
    title: () => L().boardListing,
    modules: [
      {
        no: "2.1", key: "draft",
        title: { zh: "Listing 起草", ja: "Listing 作成" },
        desc: { zh: "标题 / 五点 / Search Terms 一次成稿。", ja: "タイトル・箇条書き・Search Terms を一括生成。" },
        fields: [
          { name: "product", label: { zh: "产品名", ja: "商品名" }, ph: { zh: "例如：云感无线蓝牙耳机 Pro", ja: "例：雲感ワイヤレスイヤホン Pro" }, required: true },
          { name: "points", label: { zh: "核心卖点", ja: "主要セールスポイント" }, type: "textarea", ph: { zh: "主动降噪 / 36小时续航 / 单耳 3.8g …", ja: "ANC / 36時間再生 / 片耳3.8g …" } },
          SITE_FIELD
        ],
        prompt: (v, zh) => zh
          ? `为「${v.product}」起草亚马逊 Listing（站点 ${v.site}）。核心卖点：${v.points || "请按品类通用卖点提炼"}。请输出标题（≤75 字符）、五点描述、Search Terms 与合规提示。`
          : `「${v.product}」の Amazon Listing を作成してください（対象 ${v.site}）。主要セールスポイント：${v.points || "カテゴリ一般の訴求点で構成"}。タイトル（75文字以内）・箇条書き5点・Search Terms・規約上の注意を出力してください。`
      },
      {
        no: "2.2", key: "image",
        title: { zh: "图片合规自检", ja: "画像規約チェック" },
        desc: { zh: "白底 / 商品占比 / 文字水印逐图核查。", ja: "白背景・占有率・文字ウォーターマークを確認。" },
        fields: [
          { name: "product", label: { zh: "产品名", ja: "商品名" }, ph: { zh: "例如：云感无线蓝牙耳机 Pro", ja: "例：雲感ワイヤレスイヤホン Pro" }, required: true },
          { name: "count", label: { zh: "图片张数", ja: "画像枚数" }, type: "number", ph: { zh: "7", ja: "7" } }
        ],
        prompt: (v, zh) => zh
          ? `检查「${v.product}」的主图合规性，共 ${v.count || 7} 张。请逐图判断是否为纯白底、商品占比是否达标、是否出现文字或水印，并给出合规结论。`
          : `「${v.product}」のメイン画像の規約チェックをお願いします（全 ${v.count || 7} 枚）。各画像について純白背景か・商品占有率・文字やウォーターマークの有無を判定し、結論を出してください。`
      },
      {
        no: "2.3", key: "price",
        title: { zh: "定价策略", ja: "価格戦略" },
        desc: { zh: "建议售价 + 保本底价，守住净利率红线。", ja: "推奨価格と損益分岐価格を提示。" },
        fields: [
          { name: "product", label: { zh: "产品名", ja: "商品名" }, ph: { zh: "例如：云感无线蓝牙耳机 Pro", ja: "例：雲感ワイヤレスイヤホン Pro" }, required: true },
          { name: "competitor", label: { zh: "竞品参考价（¥）", ja: "競合参考価格（¥）" }, type: "number", ph: { zh: "299", ja: "299" } }
        ],
        prompt: (v, zh) => zh
          ? `为「${v.product}」制定定价策略，竞品参考价约 ¥${v.competitor || "未知"}。请给出建议售价、保本底价与定价理由，并说明是否适合首发低价冲量。`
          : `「${v.product}」の価格戦略を策定してください。競合参考価格 約¥${v.competitor || "不明"}。推奨価格・損益分岐価格・根拠を示し、初回の低価格戦略が適切かも述べてください。`
      },
      {
        no: "2.4", key: "fulfill",
        title: { zh: "履约建议", ja: "フルフィルメント提案" },
        desc: { zh: "FBA 还是自发货，首批备多少。", ja: "FBA か自己発送か、初回仕入れ数は。" },
        fields: [
          { name: "product", label: { zh: "产品名", ja: "商品名" }, ph: { zh: "例如：云感无线蓝牙耳机 Pro", ja: "例：雲感ワイヤレスイヤホン Pro" }, required: true },
          { name: "monthly", label: { zh: "预计月销（件）", ja: "想定月販（個）" }, type: "number", ph: { zh: "300", ja: "300" } }
        ],
        prompt: (v, zh) => zh
          ? `为「${v.product}」给出履约建议，预计月销 ${v.monthly || "未知"} 件。请建议采用 FBA 还是自发货，给出首批备货量，并说明理由与风险。`
          : `「${v.product}」のフルフィルメント提案をお願いします。想定月販 ${v.monthly || "不明"} 個。FBA か自己発送かを提案し、初回仕入れ数・根拠・リスクを述べてください。`
      },
      {
        no: "2.5", key: "free", free: true,
        title: { zh: "自由对话", ja: "フリートーク" },
        desc: { zh: "没有合适模块？直接描述你的上架问题。", ja: "該当モジュールがない場合は自由に相談。" },
        fields: []
      }
    ]
  }
};

/* ---------- 会话 ---------- */
function sidOf(board) { return localStorage.getItem(BOARDS[board].sidKey) || ""; }
function storeSid(board, sid) { localStorage.setItem(BOARDS[board].sidKey, sid); }

async function ensureSession(board, force = false) {
  if (!force && sidOf(board)) return sidOf(board);
  try {
    const res = await fetch("/api/conversation/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: "default" })
    });
    if (res.ok) {
      const j = await res.json();
      if (j && j.session_id) { storeSid(board, j.session_id); return j.session_id; }
    }
  } catch (e) { /* 后端不可达 → 本地生成 */ }
  const sid = (crypto.randomUUID ? crypto.randomUUID() : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  storeSid(board, sid);
  return sid;
}

async function askBackend(q, board) {
  const sid = await ensureSession(board);
  const res = await fetch("/api/ask", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: q, session_id: sid, user_id: "default", lang })
  });
  if (!res.ok) return null;
  const j = await res.json();
  return (j && j.reply) ? j : null;
}

/* ---------- 气泡 ---------- */
const msgsEl = board => $(`#${BOARDS[board].msgsId}`);
const scrollBottom = board => { const el = msgsEl(board); el.scrollTop = el.scrollHeight; };

function addMsg(board, who, html, cardHTML) {
  const el = msgsEl(board);
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.innerHTML = `
    <div class="msg-head"><span>${escapeHTML(who === "user" ? L().you : L().agent)}</span><span>${now()}</span></div>
    <div class="bubble">${html}${cardHTML ? `<div class="card">${cardHTML}</div>` : ""}</div>`;
  el.appendChild(div);
  scrollBottom(board);
  return div;
}

function showTyping(board) {
  const el = msgsEl(board);
  const div = document.createElement("div");
  div.className = "msg ai typing";
  div.innerHTML = `<div class="msg-head"><span>${escapeHTML(L().agent)}</span><span>${now()}</span></div>
    <div class="bubble"><i></i><i></i><i></i></div>`;
  el.appendChild(div); scrollBottom(board);
  return div;
}

/* ---------- 卡片渲染 ---------- */
const checkIcon = ok => ok ? `<span class="ck ok">✓</span>` : `<span class="ck bad">✗</span>`;

const orderCard = (o) => `
  <div class="card-title"><svg viewBox="0 0 24 24"><path d="M3 7h11v8H3zM14 10h4l3 3v2h-7z"/><circle cx="7" cy="17.4" r="1.6"/><circle cx="17.4" cy="17.4" r="1.6"/></svg>${L().card.order} ${escapeHTML(o.order_no)} · ${escapeHTML(o.carrier)}</div>
  <div class="order-row">
    <img src="${o.product.img}" alt="">
    <div><b>${escapeHTML(o.product.name)}</b><div class="sub">¥${o.product.price} × ${o.qty} · ${escapeHTML(o.paid_at)}</div></div>
  </div>
  <div class="track">${(o.steps || []).map(s => `<span class="tp ${s.state}">${escapeHTML(s.label)}</span>`).join("")}</div>`;

const recoCard = (items) => `
  <div class="card-title"><svg viewBox="0 0 24 24"><path d="m12 3 2.6 5.3L20 9l-4 3.8.9 5.6L12 15.9 7.1 18.4 8 12.8 4 9l5.4-.7z"/></svg>${L().card.reco}</div>
  <div class="link-row">${items.map(p => `
    <div class="prod-card"><img src="${p.img}" alt=""><b>${escapeHTML(p.name)}</b><div class="price"><small>¥</small>${p.price}</div></div>`).join("")}</div>`;

const reportCard = (d) => `
  <div class="card-title">${L().card.verdict} · ${escapeHTML(d.category || "")} <span class="score-tag">${escapeHTML(d.score || "")}</span><span class="verdict ${d.verdict === "建议推进" ? "go" : "warn"}">${escapeHTML(d.verdict || "")}</span></div>
  <div class="check-list">${Object.entries(d.steps || {}).map(([k, v]) => `
    <div class="check-row">${checkIcon(v.passed)}<span class="ck-name">${escapeHTML(k)}</span>
      <span class="ck-detail">${Object.entries(v).filter(([x]) => x !== "passed").map(([x, b]) => `${escapeHTML(x)}:${typeof b === "boolean" ? (b ? "✓" : "✗") : escapeHTML(String(b))}`).join(" · ")}</span>
    </div>`).join("")}</div>`;

const supplierCard = (d) => `
  <div class="card-title">${L().card.supplier} · ${escapeHTML(d.keyword || "")}</div>
  <table class="sup-table">
    <tr><th>供应商</th><th>${L().card.moq}</th><th>${L().card.unitPrice}</th><th>${L().card.lead}</th><th>评分</th></tr>
    ${(d.rows || []).map(r => `
      <tr class="${r.name === d.recommend ? "best" : ""}"><td>${r.name === d.recommend ? "★ " : ""}${escapeHTML(r.name)}<small>${escapeHTML(r.city || "")}</small></td>
      <td>${r.moq} 件</td><td>¥${r.unit_price}</td><td>${r.lead_days} 天</td><td>${r.rating}</td></tr>`).join("")}
  </table>
  <div class="recommend-line">${L().card.recommend}：<b>${escapeHTML(d.recommend || "")}</b>${d.reason ? ` —— ${escapeHTML(d.reason)}` : ""}</div>`;

const listingCard = (d) => `
  <div class="card-title">${L().card.draft} · ${escapeHTML(d.product || "")} <span class="score-tag">标题 ${d.title_len || 0} 字符</span></div>
  <div class="draft-title">${escapeHTML(d.title || "")}</div>
  <div class="sub-head">${L().card.bullets}</div>
  <ol class="bullets">${(d.bullets || []).map(b => `<li>${escapeHTML(b)}</li>`).join("")}</ol>
  <div class="sub-head">${L().card.terms}</div>
  <div class="terms">${escapeHTML(d.search_terms || "")}</div>
  <div class="tips">${(d.tips || []).map(t => `<span>${escapeHTML(t)}</span>`).join("")}</div>`;

const imageCard = (d) => `
  <div class="card-title">${L().card.images} <span class="score-tag">${d.passed_count}/${d.total}</span></div>
  <div class="check-list">${(d.detail || []).map(x => `
    <div class="check-row">${checkIcon(x.passed)}<span class="ck-name">图 ${x.image_no}</span>
      <span class="ck-detail">${x.white_bg ? "白底✓" : "白底✗"} · 占比${x.ratio_ok ? "✓" : "✗"} · ${x.no_text_watermark ? "无文字✓" : "有文字✗"}</span>
    </div>`).join("")}</div>`;

const priceCard = (d) => `
  <div class="card-title">${L().card.price} · ${escapeHTML(d.product || "")}</div>
  <div class="price-line"><span class="price-big">¥${d.suggested}</span><span class="price-sub">${L().card.suggested}</span></div>
  <div class="price-meta">竞品参考 ¥${d.competitor_ref} · ${L().card.floor} <b>¥${d.min_break_even}</b></div>
  <div class="tips">${d.hint ? `<span>${escapeHTML(d.hint)}</span>` : ""}</div>`;

const fulfillCard = (d) => `
  <div class="card-title">${L().card.fulfill} · ${escapeHTML(d.product || "")}</div>
  <div class="price-line"><span class="price-big">${escapeHTML(d.suggested_mode || "")}</span><span class="price-sub">${L().card.mode}</span></div>
  <div class="price-meta">${L().card.batch}：<b>${d.first_batch} 件</b></div>
  <div class="tips">${d.hint ? `<span>${escapeHTML(d.hint)}</span>` : ""}</div>`;

function cardFrom(a) {
  if (!a || !a.data) return "";
  if (a.intent === "order") return orderCard(a.data);
  if (a.intent === "recommend" && Array.isArray(a.data.items)) return recoCard(a.data.items);
  const t = a.data.type;
  if (t === "research_report") return reportCard(a.data);
  if (t === "supplier_compare") return supplierCard(a.data);
  if (t === "listing_draft") return listingCard(a.data);
  if (t === "image_check") return imageCard(a.data);
  if (t === "price_strategy") return priceCard(a.data);
  if (t === "fulfillment") return fulfillCard(a.data);
  return "";
}

/* ---------- 本地演示兜底（后端不可达时） ---------- */
function localAnswer(q) {
  const s = q.toLowerCase(), zh = lang === "zh";
  if (/(供应商|1688|货源|进货|采购|仕入れ)/.test(s)) {
    return { reply: zh ? "已为您找到候选货源（演示数据），详见对比卡片：" : "仕入れ先の候補です（デモデータ）。比較カードをご覧ください：",
      intent: "research", data: { type: "supplier_compare", keyword: zh ? "蓝牙耳机" : "ワイヤレスイヤホン",
        recommend: "深圳声学智造", reason: zh ? "评分 4.9 且综合分最高" : "評価4.9かつ総合スコア最高",
        rows: [
          { name: "深圳声学智造", city: "深圳", moq: 60, unit_price: 45.0, lead_days: 9, rating: 4.9 },
          { name: "东莞音频电子", city: "东莞", moq: 100, unit_price: 39.0, lead_days: 12, rating: 4.5 },
          { name: "义乌数码港·鑫声", city: "义乌", moq: 40, unit_price: 48.0, lead_days: 6, rating: 4.4 }] } };
  }
  if (/(选品|选个|热销|爆款|利润|竞争|需求|报告|選品|利益|需要)/.test(s)) {
    return { reply: zh ? "「云感耳机」选品四步结论：<b>建议推进</b>（3/3）。" : "「雲感イヤホン」の選品結論：<b>推進を推奨</b>（3/3）。",
      intent: "research", data: { type: "research_report", category: zh ? "云感耳机" : "雲感イヤホン", score: "3/3",
        verdict: zh ? "建议推进" : "推進を推奨",
        steps: {
          [zh ? "需求" : "需要"]: { passed: true, [zh ? "搜索量≥3000" : "検索量≥3000"]: true, [zh ? "售价$20~$70" : "価格$20〜$70"]: true, [zh ? "重量<2lb" : "重量<2lb"]: true },
          [zh ? "竞争" : "競合"]: { passed: true, [zh ? "首页评分≤4.3" : "上位評価≤4.3"]: true, [zh ? "平均评论≤500" : "平均レビュー≤500"]: true },
          [zh ? "利润" : "利益"]: { passed: true, margin: 0.34, profit_per_unit: 17.6 } } } };
  }
  if (/(图片|主图|合规|画像|規約)/.test(s)) {
    return { reply: zh ? "主图合规自检完成（演示数据）：" : "メイン画像の規約チェック完了（デモデータ）：",
      intent: "listing", data: { type: "image_check", passed_count: 5, total: 7,
        detail: [1, 2, 3, 4, 5].map(n => ({ image_no: n, passed: true, white_bg: true, ratio_ok: true, no_text_watermark: true }))
          .concat([{ image_no: 6, passed: false, white_bg: false, ratio_ok: true, no_text_watermark: true },
                   { image_no: 7, passed: false, white_bg: true, ratio_ok: false, no_text_watermark: false }]) } };
  }
  if (/(定价|售价|价格|価格)/.test(s)) {
    return { reply: zh ? "「云感耳机」定价建议：¥284（略低于竞品做首发）。" : "「雲感イヤホン」の価格提案：¥284（競合よりやや低めで初回投入）。",
      intent: "listing", data: { type: "price_strategy", product: zh ? "云感无线蓝牙耳机 Pro · 半入耳" : "雲感ワイヤレスイヤホン Pro",
        competitor_ref: 299, suggested: 284, min_break_even: 233,
        hint: zh ? "低于 233 元将跌破 30% 净利率红线。" : "233元を下回ると純利益率30%を割ります。" } };
  }
  if (/(履约|备货|fba|发货|フルフィルメント|発送)/.test(s)) {
    return { reply: zh ? "履约建议（演示数据）：" : "フルフィルメント提案（デモデータ）：",
      intent: "listing", data: { type: "fulfillment", product: zh ? "云感无线蓝牙耳机 Pro" : "雲感ワイヤレスイヤホン Pro",
        suggested_mode: "FBA", first_batch: 300,
        hint: zh ? "首批 300 件试销，销速稳定后转海运补货。" : "初回300個でテスト、回転が安定したら船便で補充。" } };
  }
  if (/(listing|上架|标题|五点|出品|タイトル)/.test(s)) {
    return { reply: zh ? "「云感耳机」Listing 草稿已生成（见卡片）：" : "「雲感イヤホン」の Listing 下書きを生成しました：",
      intent: "listing", data: { type: "listing_draft", product: zh ? "云感耳机" : "雲感イヤホン",
        title: "SellPilot Wireless Earbuds with ANC HiFi Stereo / 36H Playtime / IPX5 for Sports & Commuting",
        title_len: 80,
        bullets: zh
          ? ["主动降噪，通勤地铁一戴安静：双馈 ANC 降噪深度 -35dB，专注不被打扰。",
             "36 小时长续航：单次 8h + 充电盒再续 28h，出差一周不用带线。",
             "云感半入耳，久戴不痛：单耳仅 3.8g，人体工学贴合，跑步也不掉。",
             "HiFi 双单元：10mm 动圈 + 高解析解码，低音有量、人声清晰。",
             "IPX5 防水：运动流汗、小雨天都可以放心用。"]
          : ["ANC で通勤が静か：-35dB のハイブリッド ANC。",
             "36時間再生：8h + ケース28h。",
             "片耳3.8gのセミインナーで長時間でも痛くない。",
             "10mmドライバー＋高解像度デコード。",
             "IPX5 防水で運動や小雨も安心。"],
        search_terms: "bluetooth earphones anc wireless earbuds sport headset true wireless ipx5",
        tips: zh ? ["标题 ≤75 字符（亚马逊 2025 新规）", "五点每点首词大写、先答核心问题"]
                  : ["タイトルは75文字以内（Amazon 2025 の新規約）", "箇条書きは先頭を大文字に"] } };
  }
  return { reply: L().greet.replace("{name}", L().boardResearch), intent: "none", data: null };
}

/* ---------- 发送流程 ---------- */
const input = $("#input");
let busy = false;
let activeBoard = "research";
let activeModule = null;
const greeted = new Set();   // 每个板块只打一次招呼（语言切换会重渲染，不应重复问候）

async function send(text) {
  const q = (text ?? input.value).trim();
  if (!q || busy) return;
  busy = true;
  if (text === undefined) { input.value = ""; autoGrow(input); }
  const board = activeBoard;

  addMsg(board, "user", escapeHTML(q));
  const typing = showTyping(board);
  $("#hint").textContent = L().thinking;

  let a = null;
  try { a = await askBackend(q, board); } catch (e) { a = null; }
  if (!a || !a.reply) a = localAnswer(q);

  await wait(DELAY());
  typing.remove();
  addMsg(board, "ai", a.reply, cardFrom(a));
  $("#hint").textContent = L().replied;
  busy = false;
}

/* ---------- 结束谈话 ---------- */
async function endConversation() {
  const board = activeBoard;
  const sid = sidOf(board);
  let ok = !!sid;
  if (sid) {
    try {
      const res = await fetch("/api/conversation/end", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, user_id: "default" })
      });
      ok = res.ok;
    } catch (e) { ok = false; }
  }
  await ensureSession(board, true);
  addMsg(board, "ai", L()[ok ? "endDone" : "endFail"]);
}

/* ---------- 视图切换 ---------- */
function showView(id) {
  $$(".view").forEach(v => v.classList.toggle("is-active", v.id === id));
}
function renderCrumb(module) {
  const board = BOARDS[activeBoard];
  const parts = [`<span class="crumb-node" data-home>${escapeHTML(L().crumbHome)}</span>`];
  if (module) {
    parts.push(`<span class="crumb-sep">/</span><span class="crumb-node">${escapeHTML(board.no + " " + board.title())}</span>`);
    parts.push(`<span class="crumb-sep">/</span><span class="crumb-node is-current">${escapeHTML(tr(module.title))}</span>`);
  }
  $("#crumb").innerHTML = parts.join("");
  const home = $("[data-home]", $("#crumb"));
  if (home) home.addEventListener("click", goHome);
}

function goHome() {
  activeModule = null;
  renderCrumb(null);
  showView("view-home");
}

function openModule(board, key) {
  activeBoard = board;
  const mod = BOARDS[board].modules.find(m => m.key === key);
  if (!mod) return;
  activeModule = mod;

  // 切换对话流
  $$(".msgs").forEach(el => el.classList.toggle("is-active", el.id === BOARDS[board].msgsId));

  // 左侧表单
  $("#modBadge").textContent = mod.no;
  $("#modTitle").textContent = tr(mod.title);
  $("#modDesc").textContent = tr(mod.desc);
  renderForm(mod);

  // 对话流头
  $("#streamLabel").textContent = `${BOARDS[board].no} ${BOARDS[board].title()} · ${tr(mod.title)}`;
  $("#hint").textContent = L().hint;
  renderCrumb(mod);
  showView("view-module");
  scrollBottom(board);

  ensureSession(board);
  if (!greeted.has(board)) {
    greeted.add(board);
    addMsg(board, "ai", L().greet.replace("{name}", tr(mod.title)));
  }
  if (mod.free) input.focus();
}

function renderForm(mod) {
  const form = $("#modForm");
  if (mod.free || !mod.fields.length) {
    form.innerHTML = `<p class="form-tip">${escapeHTML(L().freeTip)}</p>`;
    return;
  }
  form.innerHTML = mod.fields.map(fieldHTML).join("") +
    `<button class="form-submit" type="submit">${escapeHTML(L().runModule)}</button>`;
}

function fieldHTML(f) {
  const lab = escapeHTML(tr(f.label));
  const ph = escapeHTML(f.ph ? tr(f.ph) : "");
  const req = f.required ? "required" : "";
  if (f.type === "select") {
    const opts = f.options.map(([v, t]) => `<option value="${escapeHTML(v)}">${escapeHTML(t)}</option>`).join("");
    return `<div class="field"><label>${lab}</label><select name="${f.name}">${opts}</select></div>`;
  }
  if (f.type === "textarea") {
    return `<div class="field"><label>${lab}</label><textarea name="${f.name}" placeholder="${ph}" ${req}></textarea></div>`;
  }
  // number 必须给 step="any"：默认 step=1 会让 29.9 这类小数校验失败，原生校验会静默拦住整个表单
  const num = f.type === "number" ? ' step="any" min="0" inputmode="decimal"' : "";
  return `<div class="field"><label>${lab}</label><input type="${f.type || "text"}" name="${f.name}" placeholder="${ph}"${num} ${req}></div>`;
}

/* ---------- 设置面板 ---------- */
const modal = $("#settingsModal");
const setMsg = $("#setMsg");

function openModal() { modal.classList.add("is-open"); modal.setAttribute("aria-hidden", "false"); }
function closeModal() { modal.classList.remove("is-open"); modal.setAttribute("aria-hidden", "true"); }
function msg(text, kind = "") { setMsg.className = `modal-msg ${kind}`; setMsg.textContent = text; }

/* 密钥状态说明：已配置 + 连接测试结论（未验证 / 通过 / 失败） */
function keyNoteText(j) {
  if (!j.api_key_set) return L().setKeyNone;
  const base = L().setKeyMasked(j.api_key_masked);
  if (j.key_verified === true) return base + L().keyOk;
  if (j.key_verified === false) return base + L().keyBad;
  return base + L().keyUnverified;
}

async function openSettings() {
  msg("");
  $("#setKey").value = "";
  try {
    const res = await fetch("/api/settings");
    const j = await res.json();
    $("#setUrl").value = j.base_url || "";
    $("#setModel").value = j.model || "";
    $("#setTemp").value = j.temperature ?? "";
    $("#setPerm").value = j.permission_mode || "plan";
    $("#setCallBudget").value = j.call_token_budget ?? "";
    $("#setCost").value = j.cost_budget ?? 0;
    $("#setCostCur").value = j.cost_currency || "CNY";
    $("#setCostNote").textContent = L().setCostNote(j.usd_cny_rate);
    $("#setKeyNow").textContent = keyNoteText(j);
  } catch (e) {
    $("#setKeyNow").textContent = L().statusDown;
  }
  openModal();
  $("#setKey").focus();
}

async function saveSettings() {
  const body = { persist: $("#setPersist").checked };
  const k = $("#setKey").value.trim();
  const u = $("#setUrl").value.trim();
  const m = $("#setModel").value.trim();
  const t = $("#setTemp").value.trim();
  const cb = $("#setCallBudget").value.trim();
  const cost = $("#setCost").value.trim();
  if (k) body.api_key = k;
  if (u) body.base_url = u;
  if (m) body.model = m;
  if (t !== "") body.temperature = Number(t);
  if (cb !== "") body.call_token_budget = Number(cb);
  if (cost !== "") { body.cost_budget = Number(cost); body.cost_currency = $("#setCostCur").value; }
  body.permission_mode = $("#setPerm").value;
  msg("…");
  try {
    const res = await fetch("/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
    const j = await res.json();
    if (j.errors && j.errors.length) { msg(j.errors.join("；"), "is-bad"); return; }
    if (!j.changed || !j.changed.length) { msg(L().saveNone); return; }
    msg(L().saveOk(j.changed.length, j.persisted), "is-ok");
    $("#setKey").value = "";
    $("#setKeyNow").textContent = keyNoteText({
      api_key_set: j.status.api_key_set,
      api_key_masked: j.status.api_key_masked,
      key_verified: j.status.key_verified,
    });
    applyStatus(j.status);
  } catch (e) {
    msg(L().saveFail + e.message, "is-bad");
  }
}

async function testSettings() {
  const btn = $("#setTest");
  // 带上表单当前填的值：可以「先填 Key 再点测试」，不必先保存
  const body = {};
  const k = $("#setKey").value.trim();
  const u = $("#setUrl").value.trim();
  const m = $("#setModel").value.trim();
  if (k) body.api_key = k;
  if (u) body.base_url = u;
  if (m) body.model = m;
  btn.disabled = true; msg(L().testing);
  try {
    const res = await fetch("/api/settings/test", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
    const j = await res.json();
    if (j.ok) msg(L().testOk(j.model) + (j.echo ? ` · echo: ${j.echo}` : ""), "is-ok");
    else msg(L().testFail + (j.error || ""), "is-bad");
    await refreshStatus();
    const g = await (await fetch("/api/settings")).json();
    $("#setKeyNow").textContent = keyNoteText(g);
  } catch (e) {
    msg(L().testFail + e.message, "is-bad");
  } finally { btn.disabled = false; }
}

/* ---------- 运行状态 ---------- */
function applyStatus(st) {
  const pill = $("#statusPill"), txt = $("#statusText");
  if (!st) { pill.className = "status-pill"; pill.title = ""; txt.textContent = L().statusDown; return; }
  if (!st.api_key_set) {                     // 没配密钥 → 本地兜底
    pill.className = "status-pill is-local";
    txt.textContent = L().statusLocal;
    pill.title = st.reason || "";
    return;
  }
  if (st.key_verified === true) {            // 配了密钥且连接测试通过
    pill.className = "status-pill is-live";
    txt.textContent = L().statusLive(st.model || st.configured_model || "LLM");
    pill.title = "";
    return;
  }
  if (st.key_verified === false) {           // 配了密钥但测试失败
    pill.className = "status-pill is-bad";
    txt.textContent = L().statusKeyBad;
    pill.title = st.key_error || "";
    return;
  }
  pill.className = "status-pill is-warn";    // 配了密钥但还没验证过
  txt.textContent = L().statusUnverified;
  pill.title = st.reason || "";
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    applyStatus(await res.json());
  } catch (e) { applyStatus(null); }
}

/* ---------- 语言 ---------- */
function setLang(l, announce = true) {
  lang = l;
  localStorage.setItem("sellpilot-lang", l);
  document.documentElement.lang = (l === "ja") ? "ja" : "zh-CN";
  document.title = L().docTitle;
  $("#langZH").classList.toggle("is-active", l === "zh");
  $("#langJA").classList.toggle("is-active", l === "ja");
  $("#langZH").setAttribute("aria-pressed", String(l === "zh"));
  $("#langJA").setAttribute("aria-pressed", String(l === "ja"));

  $$("[data-i18n]").forEach(el => { const v = L()[el.dataset.i18n]; if (typeof v === "string") el.textContent = v; });
  $$("[data-i18n-ph]").forEach(el => { const v = L()[el.dataset.i18nPh]; if (typeof v === "string") el.placeholder = v; });

  renderHome();
  if (activeModule) { openModule(activeBoard, activeModule.key); }
  else { renderCrumb(null); }
  refreshStatus();
  if (announce) addMsg(activeBoard, "ai", L().switched);
}

/* ---------- 总览渲染 ---------- */
function renderHome() {
  $$(".board").forEach(art => {
    const board = art.dataset.board;
    const cfg = BOARDS[board];
    // 逐条错峰入场：Listing 板整体延后一拍，形成左右次第展开的节奏
    const base = board === "listing" ? 140 : 0;
    $(".mod-grid", art).innerHTML = cfg.modules.map((m, i) => `
      <button class="mod-card" type="button" data-board="${board}" data-mod="${m.key}"
              style="animation-delay:${base + i * 55}ms">
        <span class="mod-no">${m.no}</span>
        <span class="mod-body"><b>${escapeHTML(tr(m.title))}</b><i>${escapeHTML(tr(m.desc))}</i></span>
        <span class="mod-go">→</span>
      </button>`).join("");
  });
  $$(".mod-card").forEach(btn => btn.addEventListener("click", () => openModule(btn.dataset.board, btn.dataset.mod)));
}

/* ---------- 工具 ---------- */
const autoGrow = t => { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 132) + "px"; };

/* ---------- 事件 ---------- */
$("#backBtn").addEventListener("click", goHome);
$("#brandBtn").addEventListener("click", goHome);
$("#sendBtn").addEventListener("click", () => send());
input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
input.addEventListener("input", () => autoGrow(input));

$("#modForm").addEventListener("submit", e => {
  e.preventDefault();
  const mod = activeModule;
  if (!mod || mod.free) return;
  const vals = {};
  new FormData(e.target).forEach((v, k) => { vals[k] = String(v).trim(); });
  const missing = (mod.fields || []).filter(f => f.required && !vals[f.name]).map(f => tr(f.label));
  if (missing.length) {
    $("#hint").textContent = L().required + missing.join(" / ");
    const first = $(`[name="${mod.fields.find(f => f.required && !vals[f.name]).name}"]`, e.target);
    if (first) first.focus();
    return;
  }
  send(mod.prompt(vals, lang === "zh"));
});

$("#endBtn").addEventListener("click", endConversation);
$("#clearBtn").addEventListener("click", () => {
  const sid = sidOf(activeBoard);
  if (sid) {
    fetch("/api/clear", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sid })
    }).catch(() => {});
  }
  msgsEl(activeBoard).innerHTML = "";
  addMsg(activeBoard, "ai", L().cleared);
});

$("#settingsBtn").addEventListener("click", openSettings);
$("#settingsClose").addEventListener("click", closeModal);
$$("[data-close]").forEach(el => el.addEventListener("click", closeModal));
$("#setSave").addEventListener("click", saveSettings);
$("#setTest").addEventListener("click", testSettings);
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

$("#langZH").addEventListener("click", () => setLang("zh"));
$("#langJA").addEventListener("click", () => setLang("ja"));

/* ---------- 启动 ---------- */
renderHome();
setLang(lang, false);
refreshStatus();
