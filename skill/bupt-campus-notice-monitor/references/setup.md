# BUPT Campus Notice Monitor — Setup Reference

This file is for initializing Iris/Asgard configuration for 北京邮电大学 only.

## Dependencies

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Optional for JS-rendered pages:

```bash
.venv\Scripts\pip install playwright
.venv\Scripts\playwright install chromium
```

## .env Template

Store secrets here, not in `config.yaml`.

```ini
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini

MY_BUPT_USERNAME=2024xxxxxx
MY_BUPT_PASSWORD=your_bupt_password
MY_BUPT_COOKIE=

UCLOUD_USERNAME=2024xxxxxx
UCLOUD_PASSWORD=your_bupt_password
UCLOUD_COOKIE=
UCLOUD_TOKEN=
UCLOUD_USER_ID=

EMAIL_SMTP_HOST=smtp.example.com
EMAIL_SMTP_PORT=465
EMAIL_USE_SSL=true
EMAIL_USERNAME=your_email@example.com
EMAIL_PASSWORD=mail_app_password
EMAIL_FROM=your_email@example.com
EMAIL_TO=target@example.com
```

## Required BUPT Auth Config

```yaml
auth:
  enabled: true
  type: "cas"
  login_url: "https://auth.bupt.edu.cn/authserver/login"
  service_url: "http://my.bupt.edu.cn/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1154"
  username: "${MY_BUPT_USERNAME}"
  password: "${MY_BUPT_PASSWORD}"

cookies:
  header: "${MY_BUPT_COOKIE}"
  map: {}
```

Use `cookies.header` only when CAS login cannot pass automatically.

## BUPT Portal Config

Keep these four BUPT sources unless the user explicitly disables one.

```yaml
portals:
  - name: "校内通知"
    url: "http://my.bupt.edu.cn/list.jsp?totalpage=30&PAGENUM={page}&urltype=tree.TreeTempUrl&wbtreeid=1154"
    source: "北邮校园网"
    pages: 2
    page_start: 0
    selectors:
      item: "ul.newslist.list-unstyled > li"
      title: "a"
      link: "a"
      published_at: "span.time"
      source: "span.author"
      detail_content:
        - "#vsb_content"
        - ".article"
        - ".v_news_content"

  - name: "办事指南"
    url: "http://my.bupt.edu.cn/list.jsp?totalpage=30&PAGENUM={page}&urltype=tree.TreeTempUrl&wbtreeid=1524"
    source: "北邮校园网"
    pages: 1
    page_start: 0
    selectors:
      item: "ul.newslist.list-unstyled > li"
      title: "a"
      link: "a"
      published_at: "span.time"
      source: "span.author"
      detail_content: ["#vsb_content", ".article", ".v_news_content"]

  - name: "校园新闻"
    url: "http://my.bupt.edu.cn/list.jsp?totalpage=30&PAGENUM={page}&urltype=tree.TreeTempUrl&wbtreeid=1221"
    source: "北邮校园网"
    pages: 1
    page_start: 0
    selectors:
      item: "ul.newslist.list-unstyled > li"
      title: "a"
      link: "a"
      published_at: "span.time"
      source: "span.author"
      detail_content: ["#vsb_content", ".article", ".v_news_content"]

  - name: "规章制度"
    url: "http://my.bupt.edu.cn/list.jsp?totalpage=30&PAGENUM={page}&urltype=tree.TreeTempUrl&wbtreeid=1536"
    source: "北邮校园网"
    pages: 1
    page_start: 0
    selectors:
      item: "ul.newslist.list-unstyled > li"
      title: "a"
      link: "a"
      published_at: "span.time"
      source: "span.author"
      detail_content: ["#vsb_content", ".article", ".v_news_content"]
```

## User Profile Config

Example for a BUPT CS freshman in Shahe:

```yaml
assistant:
  name: "阿斯加德"
  user_profile: |
    我是北京邮电大学计算机学院大一学生，在沙河校区。
    请优先关注：计算机学院、大一/大二、本科低年级、新生、沙河校区、竞赛报名、选拔、训练营、创新项目、科研机会、选课、考试、成绩、补考、转专业、奖学金和重要截止时间。
  extra_instruction: |
    如果标题明显是干部任免、纯行政背景信息或和普通学生关系很弱，直接降为低优先级。
  priority_keywords:
    - "计算机学院"
    - "大一"
    - "大二"
    - "沙河"
    - "竞赛"
    - "报名"
    - "选拔"
    - "训练营"
    - "创新"
    - "程序设计"
    - "实验班"
  ignore_keywords:
    - "干部"
    - "任免"
    - "党委"
```

## UCloud Homework → Evening Digest

Enable this when the user chooses “抓取作业 -> 晚报”.

```yaml
ucloud:
  enabled: true
  api_base_url: "https://apiucloud.bupt.edu.cn/ykt-site"
  homepage_url: "https://ucloud.bupt.edu.cn/"
  login_url: "https://auth.bupt.edu.cn/authserver/login"
  service_url: "https://ucloud.bupt.edu.cn"
  username: "${UCLOUD_USERNAME}"
  password: "${UCLOUD_PASSWORD}"
  token: "${UCLOUD_TOKEN}"
  user_id: "${UCLOUD_USER_ID}"
  cookie_header: "${UCLOUD_COOKIE}"
  cookie_map: {}
  max_items: 30
```

If CAS login is unreliable, ask the user for `UCLOUD_COOKIE` or token values exported from a logged-in browser session.

## LLM Config

```yaml
llm:
  enabled: true
  api_key: "${OPENAI_API_KEY}"
  base_url: "${OPENAI_BASE_URL}"
  model: "${AI_MODEL}"
  temperature: 0.1
  max_input_chars: 4000
  timeout_seconds: 60
  title_batch_size: 40
  body_batch_size: 8
  body_excerpt_chars: 1800
  backup_api_key: "${BACKUP_OPENAI_API_KEY}"
  backup_base_url: "${BACKUP_OPENAI_BASE_URL}"
```

## Scheduling Presets

### Default: 早报 + 晚报 + 白天 heartbeat

```yaml
runtime:
  polling_interval: 1800

scheduler:
  enabled: true
  heartbeat_interval_hours: 2
  active_start: "08:00"
  active_end: "22:00"
  morning_digest_time: "08:00"
  evening_digest_time: "20:00"
  daytime_email_levels:
    - "important"
    - "watch"
  digest_only_portals:
    - "校园新闻"
  silent_when_empty: true
```

### 晚报只重点看作业

```yaml
ucloud:
  enabled: true
scheduler:
  evening_digest_time: "20:00"
```

Evening renderer prioritizes UCloud homework-style items. Keep normal portal scraping enabled unless the user explicitly wants homework-only.

### 早报看昨日校园新闻

```yaml
scheduler:
  morning_digest_time: "08:00"
  digest_only_portals:
    - "校园新闻"
```

This keeps the morning digest focused on the BUPT “校园新闻” portal. Do not promise general notice summaries unless the script is extended to populate them.

### 午报

Option A — digest-style noon report:

```yaml
scheduler:
  morning_digest_time: "12:00"
```

Option B — lightweight noon scan:

```yaml
scheduler:
  active_start: "12:00"
  active_end: "13:00"
  heartbeat_interval_hours: 1
```

Use option A if the user expects a structured digest. Use option B if they only want a quick scan.

### 自由时间轮询

For example, poll from 09:30 to 23:30 every 3 hours:

```yaml
runtime:
  polling_interval: 1800
scheduler:
  active_start: "09:30"
  active_end: "23:30"
  heartbeat_interval_hours: 3
  morning_digest_time: "09:30"
  evening_digest_time: "22:30"
```

## Commands

```bash
python -m src --once --preview      # test scrape + AI analysis without sending email
python -m src --once                # one real cycle
python -m src --email-test morning_digest
python -m src --email-test evening_digest
python -m src --loop                # internal scheduler loop
```

Use `--loop` for normal operation on the campus-network server. Use external cron/Hermes scheduling only if the user wants one-shot executions instead of the built-in scheduler.
