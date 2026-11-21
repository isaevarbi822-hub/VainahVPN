package app.vainah.vpn

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.clerk.api.Clerk
import com.clerk.ui.auth.AuthView
import com.clerk.ui.userbutton.UserButton
import com.google.i18n.phonenumbers.PhoneNumberUtil
import java.util.Locale

/**
 * User chooses ONE method. The native Clerk AuthView owns OTPs, account
 * creation and sessions. Never create a parallel phone/email auth backend.
 */
class ClerkLoginActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!BuildConfig.VAINAH_CLERK_ENABLED ||
            !ClerkPublicKey.isConfigured(BuildConfig.VAINAH_CLERK_PUBLISHABLE_KEY)) {
            finish()
            return
        }
        setContent {
            val initialized by Clerk.isInitialized.collectAsStateWithLifecycle()
            val session by Clerk.sessionFlow.collectAsStateWithLifecycle()
            var chosenIdentifier by rememberSaveable { mutableStateOf<String?>(null) }

            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                when {
                    !initialized -> Text("Подключаем Clerk…")
                    session != null -> Column(
                        Modifier.padding(20.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(14.dp)
                    ) {
                        Text("Вход в Vainah VPN подтверждён")
                        UserButton()
                        Button(onClick = { finish() }) { Text("Вернуться в Vainah VPN") }
                    }
                    chosenIdentifier != null -> {
                        // Clerk routes +E164 identifiers into its phone flow.
                        // It remains responsible for SMS availability and delivery.
                        val identifier = chosenIdentifier ?: ""
                        AuthView(
                            initialIdentifier = identifier,
                            persistIdentifiers = false,
                            onAuthComplete = { finish() },
                            onDismiss = { chosenIdentifier = null }
                        )
                    }
                    else -> MethodSelector(
                        onContinue = { chosenIdentifier = it },
                        onCancel = { finish() }
                    )
                }
            }
        }
    }
}

private data class DialCountry(val region: String, val name: String, val dialCode: Int) {
    val label: String get() = "$name (+$dialCode)"
}

/** All geographic regions in current libphonenumber calling-code metadata. */
private fun countryOptions(): List<DialCountry> {
    val phone = PhoneNumberUtil.getInstance()
    val language = Locale("ru")
    return phone.supportedRegions
        .mapNotNull { region ->
            val code = phone.getCountryCodeForRegion(region)
            if (code <= 0) null else DialCountry(
                region = region,
                name = Locale("", region).getDisplayCountry(language)
                    .ifBlank { region },
                dialCode = code
            )
        }
        .sortedWith(compareBy<DialCountry> { it.name }.thenBy { it.region })
}

@Composable
private fun MethodSelector(onContinue: (String) -> Unit, onCancel: () -> Unit) {
    val phoneUtil = remember { PhoneNumberUtil.getInstance() }
    val countries = remember { countryOptions() }
    var method by rememberSaveable { mutableStateOf("email") }
    var email by rememberSaveable { mutableStateOf("") }
    var nationalNumber by rememberSaveable { mutableStateOf("") }
    val defaultRegion = remember {
        Locale.getDefault().country.uppercase(Locale.ROOT)
            .takeIf { region -> countries.any { it.region == region } }
            ?: "NO"
    }
    var countryRegion by rememberSaveable { mutableStateOf(defaultRegion) }
    var showCountryPicker by rememberSaveable { mutableStateOf(false) }
    var countrySearch by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    val country = countries.firstOrNull { it.region == countryRegion }
        ?: countries.firstOrNull { it.region == "NO" }
        ?: countries.first()

    Column(
        Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(15.dp)
    ) {
        Text("Vainah VPN")
        Text("Вход или регистрация")
        Text("Выбери один способ: электронную почту ИЛИ номер телефона.")
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            FilterChip(
                selected = method == "email",
                onClick = { method = "email"; error = null },
                label = { Text("По email") }
            )
            FilterChip(
                selected = method == "phone",
                onClick = { method = "phone"; error = null },
                label = { Text("По телефону") }
            )
        }

        if (method == "email") {
            OutlinedTextField(
                value = email,
                onValueChange = { email = it.take(254); error = null },
                label = { Text("Электронная почта") },
                placeholder = { Text("name@example.com") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                modifier = Modifier.fillMaxWidth()
            )
            Text("Код подтверждения придёт на выбранную почту через Clerk.")
        } else {
            TextButton(onClick = { showCountryPicker = true }) {
                Text("Страна: ${country.label} ▾")
            }
            OutlinedTextField(
                value = nationalNumber,
                onValueChange = { nationalNumber = it.take(32); error = null },
                label = { Text("Номер телефона") },
                placeholder = { Text("+${country.dialCode} …") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                modifier = Modifier.fillMaxWidth()
            )
            Text("Все международные коды доступны в списке. SMS придёт, если страна разрешена в настройках Clerk.")
        }
        if (error != null) {
            Text(error ?: "")
        }
        Button(
            onClick = {
                val normalized = if (method == "email") {
                    email.trim().lowercase(Locale.ROOT).takeIf { value ->
                        value.length <= 254 &&
                            Regex("^[^\\s@<>]{1,64}@[a-z0-9-]+(?:\\.[a-z0-9-]+)+$").matches(value)
                    }
                } else {
                    runCatching {
                        val input = nationalNumber.trim()
                        // Both local numbers and complete +E164 numbers are supported.
                        val parsed = phoneUtil.parse(
                            input,
                            if (input.startsWith("+")) "ZZ" else country.region
                        )
                        if (phoneUtil.isValidNumber(parsed)) {
                            phoneUtil.format(parsed, PhoneNumberUtil.PhoneNumberFormat.E164)
                        } else null
                    }.getOrNull()
                }
                if (normalized != null) onContinue(normalized)
                else error = if (method == "email") "Проверь адрес почты."
                else "Проверь номер и международный код страны."
            },
            modifier = Modifier.fillMaxWidth()
        ) { Text("Продолжить с ${if (method == "email") "почтой" else "телефоном"}") }
        TextButton(onClick = onCancel) { Text("Отмена") }
    }

    if (showCountryPicker) {
        val filtered = remember(countries, countrySearch) {
            val query = countrySearch.trim().lowercase(Locale.ROOT)
            countries.filter { c ->
                query.isBlank() ||
                    c.name.lowercase(Locale.ROOT).contains(query) ||
                    c.region.lowercase(Locale.ROOT).contains(query) ||
                    "+${c.dialCode}".contains(query)
            }
        }
        AlertDialog(
            onDismissRequest = { showCountryPicker = false; countrySearch = "" },
            title = { Text("Международный код") },
            text = {
                Column {
                    OutlinedTextField(
                        value = countrySearch,
                        onValueChange = { countrySearch = it.take(64) },
                        label = { Text("Страна или +код") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    LazyColumn(Modifier.heightIn(max = 360.dp)) {
                        items(filtered, key = { it.region }) { option ->
                            TextButton(
                                onClick = {
                                    countryRegion = option.region
                                    countrySearch = ""
                                    showCountryPicker = false
                                    error = null
                                },
                                modifier = Modifier.fillMaxWidth()
                            ) { Text(option.label) }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    showCountryPicker = false
                    countrySearch = ""
                }) { Text("Закрыть") }
            }
        )
    }
}
