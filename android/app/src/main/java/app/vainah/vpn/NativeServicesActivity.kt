package app.vainah.vpn

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.ArrayAdapter
import android.text.InputType
import android.widget.TextView
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * Genuine native customer services. Uses the same encrypted cookie as
 * NativeCabinetActivity; no WebView, fake tickets, mock device sessions or
 * checkout secrets. Server-side ownership and rate limits remain authoritative.
 */
class NativeServicesActivity : Activity() {
    private lateinit var api: NativeCabinetApi
    private val worker = Executors.newSingleThreadExecutor()
    private var section = "support"
    private var message = ""
    private var busy = false
    private var supportConfig: JSONObject? = null
    private var tickets: JSONObject? = null
    private var devices: JSONObject? = null
    private var limits: JSONObject? = null
    private var reminders: JSONObject? = null
    private var conversation: JSONObject? = null
    private var selectedTicket: String? = null

    private val ink = VainahDesign.ink
    private val muted = VainahDesign.muted
    private val accent = VainahDesign.purple

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = NativeCabinetApi(this)
        section = savedInstanceState?.getString("section")
            ?: intent.getStringExtra("section").orEmpty()
        if (section !in listOf("support", "devices", "reminders"))
            section = "support"
        window.statusBarColor = VainahDesign.background
        window.navigationBarColor = VainahDesign.background
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        render()
    }

    override fun onSaveInstanceState(out: Bundle) {
        out.putString("section", section)
        super.onSaveInstanceState(out)
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }

    private fun dp(x: Int) = VainahUi.dp(this, x)
    private fun col() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
    }
    private fun add(parent: LinearLayout, child: View, top: Int = 0) {
        parent.addView(child, LinearLayout.LayoutParams(-1, -2).apply {
            topMargin = dp(top)
        })
    }
    private fun t(value: String, size: Float = 13f, bold: Boolean = false,
                  color: Int = ink): TextView = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color)
        if (bold) typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
        setLineSpacing(dp(2).toFloat(), 1f)
    }
    private fun card() = col().apply {
        setPadding(dp(17), dp(15), dp(17), dp(17))
        background = VainahUi.cardBackground(this@NativeServicesActivity)
        elevation = dp(2).toFloat()
    }
    private fun action(text: String, primary: Boolean = false) =
        Button(this).apply {
            this.text = text
            textSize = 12f
            isAllCaps = false
            setTextColor(if (primary) Color.WHITE else ink)
            background = VainahUi.buttonBackground(this@NativeServicesActivity, primary)
            minHeight = dp(45)
            setPadding(dp(12), 0, dp(12), 0)
        }
    private fun edit(hint: String, lines: Int = 1) = EditText(this).apply {
        this.hint = hint
        textSize = 13f
        setTextColor(ink)
        setHintTextColor(muted)
        setPadding(dp(12), dp(11), dp(12), dp(11))
        if (lines > 1) {
            minLines = lines
            maxLines = lines + 4
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
        } else {
            setSingleLine(true)
        }
        background = GradientDrawable().apply {
            setColor(Color.rgb(251, 249, 255))
            cornerRadius = dp(12).toFloat()
            setStroke(dp(1), VainahDesign.border)
        }
    }
    private fun <T> request(block: () -> T, onReply: (Result<T>) -> Unit) {
        if (busy) return
        busy = true
        worker.execute {
            val reply = runCatching(block)
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                busy = false
                onReply(reply)
            }
        }
    }

    private fun refresh() {
        if (!api.hasSession()) {
            render()
            return
        }
        request({
            when(section) {
                "support" -> {
                    val config = runCatching {
                        api.get("/api/support/config").json
                    }.getOrNull()
                    val rows = api.get("/api/support/tickets")
                    val thread = selectedTicket?.let {
                        CabinetServicePaths.messagePath(it)?.let { path ->
                            api.get(path).takeIf { reply -> reply.ok }?.json
                        }
                    }
                    arrayOf(config, if (rows.ok) rows.json else null, thread)
                }
                "devices" -> {
                    val listed = api.get("/api/account/devices")
                    val verified = runCatching {
                        api.get("/api/account/devices/limits").json
                    }.getOrNull()
                    arrayOf(if (listed.ok) listed.json else null, verified)
                }
                else -> {
                    val state = api.get("/api/account/reminder-preference")
                    arrayOf(if (state.ok) state.json else null)
                }
            }
        }) { result ->
            result.onSuccess { values ->
                when(section) {
                    "support" -> {
                        supportConfig = values.getOrNull(0)
                        tickets = values.getOrNull(1)
                        conversation = values.getOrNull(2)
                    }
                    "devices" -> {
                        devices = values.getOrNull(0)
                        limits = values.getOrNull(1)
                    }
                    else -> reminders = values.getOrNull(0)
                }
                if (values.firstOrNull() == null) {
                    message = "Сервис временно недоступен. Проверь вход и подключение."
                }
            }.onFailure {
                message = "Данные не загрузились. Попробуй обновить страницу."
            }
            render()
        }
    }

    private fun render() {
        val root = col().apply {
            background = VainahUi.pageBackground()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                setOnApplyWindowInsetsListener { view, insets ->
                    val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars())
                    view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                    insets
                }
            } else fitsSystemWindows = true
        }
        val body = col().apply {
            setPadding(dp(16), dp(10), dp(16), dp(28))
        }
        val scroll = ScrollView(this)
        scroll.addView(body)
        root.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))

        val header = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        val back = action("‹")
        back.contentDescription = "Назад в личный кабинет"
        header.addView(back, LinearLayout.LayoutParams(dp(46), dp(46)))
        back.setOnClickListener { finish() }
        header.addView(VainahShieldView(this), LinearLayout.LayoutParams(dp(34), dp(34)))
        header.addView(t("VainahVPN", 19f, true), LinearLayout.LayoutParams(0, -2, 1f).apply {
            marginStart = dp(9)
        })
        val update = action("↻")
        update.contentDescription = "Обновить данные"
        update.isEnabled = !busy
        header.addView(update, LinearLayout.LayoutParams(dp(46), dp(46)))
        update.setOnClickListener { message = ""; refresh() }
        add(body, header)
        add(body, t(when(section) {
            "support" -> "Поддержка"
            "devices" -> "Мои устройства"
            else -> "Напоминания"
        }, 26f, true), 14)

        message.takeIf { it.isNotBlank() }?.let {
            add(body, VainahUi.infoStrip(this, it), 10)
        }
        if (busy) add(body, VainahUi.infoStrip(this, "Обновляем данные…"), 8)
        if (!api.hasSession()) {
            val entry = card()
            add(body, entry, 13)
            add(entry, t("Сначала войди в аккаунт", 18f, true))
            add(entry, t("Один вход используется для кабинета, " +
                "поддержки, устройств и напоминаний.", 12f, color = muted), 9)
            val button = action("Войти в VainahVPN", true)
            add(entry, button, 11)
            button.setOnClickListener {
                startActivity(Intent(this, NativeCabinetActivity::class.java))
            }
            setContentView(root)
            return
        }
        when(section) {
            "support" -> renderSupport(body)
            "devices" -> renderDevices(body)
            else -> renderReminders(body)
        }
        setContentView(root)
    }

    private fun renderSupport(body: LinearLayout) {
        val intro = card()
        add(body, intro, 13)
        add(intro, t("Напиши оператору", 18f, true))
        add(intro, t("Не отправляй VPN-ключи, ссылки подписок и " +
            "пароли. Ответ появится прямо здесь.", 12f, color = muted), 8)
        if (supportConfig?.optBoolean("available") == false) {
            add(intro, VainahUi.infoStrip(this,
                "Приём обращений временно отключён на сервере."), 9)
        }
        val categories = arrayOf(
            "Подключение", "Оплата", "Аккаунт", "Другое"
        )
        val codes = arrayOf("connection", "payment", "account", "other")
        val spinner = Spinner(this).apply {
            adapter = ArrayAdapter(this@NativeServicesActivity,
                android.R.layout.simple_spinner_dropdown_item, categories.toList())
            contentDescription = "Тема обращения"
        }
        add(intro, spinner, 11)
        val input = edit("Опиши проблему без личных данных", 3)
        add(intro, input, 10)
        val submit = action("Отправить обращение", true)
        submit.isEnabled = !busy && supportConfig?.optBoolean("available") == true
        add(intro, submit, 10)
        submit.setOnClickListener {
            val category = codes[spinner.selectedItemPosition.coerceIn(0, 3)]
            val draft = input.text.toString().trim()
            if (!SupportDraftPolicy.category(category) ||
                !SupportDraftPolicy.safe(draft, 12)) {
                message = "Опиши проблему минимум в 12 символах, " +
                    "без ссылок, ключей и паролей."
                render()
                return@setOnClickListener
            }
            request({
                api.post("/api/support/tickets", JSONObject()
                    .put("category", category)
                    .put("message", draft)
                    .put("notify_email", false))
            }) { reply ->
                message = if (reply.getOrNull()?.ok == true)
                    "Обращение создано. Проверь его в списке ниже."
                else "Не удалось создать обращение. Проверь аккаунт и повтори."
                refresh()
            }
        }

        val history = card()
        add(body, history, 12)
        add(history, t("Мои обращения", 18f, true))
        val items = tickets?.optJSONArray("items")
        if (items == null) {
            add(history, t("Список ещё не загружен.", 12f, color = muted), 9)
        } else if (items.length() == 0) {
            add(history, t("Обращений пока нет.", 12f, color = muted), 9)
        } else {
            for (i in 0 until minOf(items.length(), 15)) {
                val item = items.optJSONObject(i) ?: continue
                val id = item.optString("id")
                val category = item.optString("category", "other")
                val status = item.optString("status", "open")
                add(history, VainahUi.detailRow(this,
                    category.replaceFirstChar { it.uppercaseChar() },
                    when(status) {
                        "answered" -> "Есть ответ"
                        "closed" -> "Закрыто"
                        else -> "Открыто"
                    }, if(status == "answered") VainahUi.Tone.SUCCESS
                    else VainahUi.Tone.NEUTRAL), 10)
                if (CabinetServicePaths.messagePath(id) != null) {
                    val view = action(if (selectedTicket == id) "Скрыть переписку"
                        else "Открыть переписку")
                    add(history, view, 4)
                    view.setOnClickListener {
                        selectedTicket = if (selectedTicket == id) null else id
                        conversation = null
                        refresh()
                    }
                }
            }
        }
        if (selectedTicket != null) renderConversation(body)
    }

    private fun renderConversation(body: LinearLayout) {
        val thread = card()
        add(body, thread, 12)
        add(thread, t("Переписка с поддержкой", 18f, true))
        val items = conversation?.optJSONArray("items")
        if (items == null) add(thread, t("Загружаем сообщения…", 12f,
            color = muted), 9)
        else for (i in 0 until minOf(50, items.length())) {
            val item = items.optJSONObject(i) ?: continue
            val who = if(item.optString("sender") == "operator")
                "Оператор" else "Вы"
            add(thread, t(who + ": " + item.optString("message").take(1500),
                12f, color = ink), 10)
        }
        val input = edit("Ответить оператору (без ссылок)", 2)
        add(thread, input, 12)
        val send = action("Отправить ответ", true)
        send.isEnabled = !busy && selectedTicket != null
        add(thread, send, 9)
        send.setOnClickListener {
            val path = selectedTicket?.let(CabinetServicePaths::messagePath)
            val draft = input.text.toString().trim()
            if (path == null || !SupportDraftPolicy.safe(draft, 4)) {
                message = "Ответ должен содержать 4–1500 символов без ссылок."
                render()
                return@setOnClickListener
            }
            request({ api.post(path, JSONObject().put("message", draft)) }) { outcome ->
                message = if (outcome.getOrNull()?.ok == true)
                    "Ответ отправлен." else "Не удалось отправить ответ."
                refresh()
            }
        }
    }

    private fun renderDevices(body: LinearLayout) {
        val panel = card()
        add(body, panel, 13)
        add(panel, t("Именованные устройства", 18f, true))
        add(panel, VainahUi.infoStrip(this,
            "Это заметки об устройствах аккаунта, НЕ список " +
                "активных VPN-сеансов. Удаление записи не отключит VPN."), 10)
        val verified = limits?.opt("plan_device_limit")
        add(panel, VainahUi.detailRow(this, "Устройств по тарифу",
            if (verified is Int && verified > 0) verified.toString()
            else "Не подтверждено"), 10)
        val items = devices?.optJSONArray("items")
        add(panel, VainahUi.detailRow(this, "Сохранено названий",
            items?.length()?.toString() ?: "Нет данных"), 7)
        if (items != null) for (i in 0 until minOf(items.length(), 12)) {
            val item = items.optJSONObject(i) ?: continue
            add(panel, VainahUi.detailRow(this,
                item.optString("name", "Устройство").take(40),
                item.optString("platform", "other").take(12)), 8)
        }
        val field = edit("Например: Samsung Galaxy")
        add(panel, field, 12)
        val addDevice = action("Сохранить название устройства", true)
        addDevice.isEnabled = !busy && items != null && items.length() < 12
        add(panel, addDevice, 8)
        addDevice.setOnClickListener {
            val name = field.text.toString().trim()
            if (name.length !in 1..40 || name.any { it.isISOControl() }) {
                message = "Введи название от 1 до 40 символов."
                render()
                return@setOnClickListener
            }
            request({
                api.post("/api/account/devices", JSONObject()
                    .put("name", name).put("platform", "android"))
            }) { response ->
                message = if(response.getOrNull()?.ok == true)
                    "Название устройства сохранено."
                else "Запись не создана. Возможно, лимит списка достигнут."
                refresh()
            }
        }
    }

    private fun renderReminders(body: LinearLayout) {
        val panel = card()
        add(body, panel, 13)
        add(panel, t("Оповещения о продлении", 18f, true))
        add(panel, VainahUi.infoStrip(this,
            "Настройка записывается на сервере. Письма приходят только " +
                "если оператор запустил настоящую рассылку."), 10)
        val ready = reminders?.optBoolean("delivery_active") == true
        val enabled = reminders?.optBoolean("enabled") == true
        add(panel, VainahUi.detailRow(this, "Расписание рассылки",
            if (ready) "Подтверждено" else "Пока не запущено",
            if (ready) VainahUi.Tone.SUCCESS else VainahUi.Tone.WARNING), 11)
        add(panel, VainahUi.detailRow(this, "Мои напоминания",
            if (enabled) "Разрешены" else "Выключены",
            if (enabled) VainahUi.Tone.PURPLE else VainahUi.Tone.NEUTRAL), 7)
        val toggle = action(if (enabled) "Отключить напоминания"
            else "Включить напоминания", true)
        toggle.isEnabled = !busy && reminders != null
        add(panel, toggle, 12)
        toggle.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Изменить напоминания?")
                .setMessage(if (ready) "Сохранить выбор в личном кабинете?"
                    else "Настройка сохранится, но рассылка ещё не работает.")
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Сохранить") { _, _ ->
                    request({
                        api.post("/api/account/reminder-preference",
                            JSONObject().put("enabled", !enabled))
                    }) { response ->
                        message = if(response.getOrNull()?.ok == true)
                            "Настройка обновлена на сервере."
                        else "Не удалось изменить настройку."
                        refresh()
                    }
                }.show()
        }
    }
}
