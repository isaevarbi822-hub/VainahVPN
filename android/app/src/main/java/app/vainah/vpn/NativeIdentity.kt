package app.vainah.vpn

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Mobile commerce transport only. Clerk Android SDK owns authentication,
 * email/SMS verification, token renewal and secure credential storage.
 * The app never creates or stores its own sign-in tokens.
 */
class NativeIdentity(context:Context) {
    private val prefs=context.getSharedPreferences("vainah_native_orders_v2",Context.MODE_PRIVATE)
    fun lastOrder():String?=prefs.getString("last_order",null)
    fun saveOrder(id:String){
        if(Regex("^[a-f0-9-]{36}$",RegexOption.IGNORE_CASE).matches(id))
            prefs.edit().putString("last_order",id).apply()
    }

    data class Account(val authenticated:Boolean,val verifiedDeliveryEmail:Boolean)
    data class Invoice(val orderId:String,val payUrl:String)
    data class Order(val status:String,val delivery:String,
        val subscriptionUrl:String?,val emailState:String)

    companion object {
        private const val ORIGIN="https://vainahvpnbot0.netlify.app"
        private fun exchange(endpoint:String,body:JSONObject?,clerkJwt:String):JSONObject {
            if(!Regex("^[A-Za-z0-9._-]{40,8192}$").matches(clerkJwt))
                throw IllegalArgumentException("Invalid session")
            val conn=URL(ORIGIN+"/.netlify/functions/"+endpoint)
                .openConnection() as HttpURLConnection
            try{
                conn.connectTimeout=7000;conn.readTimeout=12000
                conn.instanceFollowRedirects=false;conn.useCaches=false
                conn.requestMethod=if(body==null)"GET" else "POST"
                conn.doOutput=body!=null
                conn.setRequestProperty("Accept","application/json")
                conn.setRequestProperty("Authorization","Bearer "+clerkJwt)
                if(body!=null){
                    conn.setRequestProperty("Content-Type","application/json")
                    conn.outputStream.use{it.write(body.toString().toByteArray(Charsets.UTF_8))}
                }
                if(conn.responseCode !in 200..299)
                    throw IllegalStateException("Сервер отклонил запрос (HTTP "+conn.responseCode+").")
                if(conn.contentLengthLong>20_000)
                    throw IllegalStateException("Response too large")
                val bytes=java.io.ByteArrayOutputStream()
                conn.inputStream.use{input->
                    val block=ByteArray(4096)
                    while(true){
                        val n=input.read(block);if(n<0)break
                        if(bytes.size()+n>20_000)throw IllegalStateException("Response too large")
                        bytes.write(block,0,n)
                    }
                }
                return JSONObject(bytes.toString("UTF-8"))
            }finally{conn.disconnect()}
        }
        fun account(jwt:String):Account {
            val result=exchange("mobile-account",null,jwt)
            return Account(
                authenticated=result.optBoolean("authenticated",false),
                verifiedDeliveryEmail=result.optBoolean("emailVerified",false)
            )
        }

        fun createInvoice(jwt:String,planId:String):Invoice {
            if(VainahPlans.all.none{it.id==planId})throw IllegalArgumentException("Bad plan")
            val data=exchange("mobile-checkout",JSONObject().put("plan",planId),jwt)
            val url=data.getString("payUrl")
            val target=URL(url)
            if(target.protocol!="https"||target.host!="pay.rollypay.io"||
                target.port!=-1||target.userInfo!=null||target.ref!=null||
                !Regex("^/pay/[A-Za-z0-9][A-Za-z0-9_-]{5,255}/?$").matches(target.path))
                throw IllegalStateException("Unsafe payment address")
            return Invoice(data.getString("orderId"),url)
        }
        fun latestOrder(jwt:String,preferredId:String?=null):String? {
            val data=exchange("mobile-orders",null,jwt)
            val list=data.optJSONArray("orders")?:return null
            if(list.length()==0)return null
            val ids=(0 until list.length()).mapNotNull { i ->
                list.optJSONObject(i)?.optString("orderId")
                    ?.takeIf { it.matches(Regex("^[a-fA-F0-9-]{36}$")) }
            }
            // Old local state is NOT proof of ownership; Clerk-owned history is.
            if(preferredId!=null && ids.contains(preferredId))return preferredId
            val pending=data.optString("latestOutstandingOrderId","")
            if(ids.contains(pending))return pending
            val delivered=data.optString("latestDeliveredOrderId","")
            if(ids.contains(delivered))return delivered
            return ids.firstOrNull()
        }
        fun readOrder(jwt:String,id:String):Order {
            if(!Regex("^[a-f0-9-]{36}$",RegexOption.IGNORE_CASE).matches(id))
                throw IllegalArgumentException("Bad order ID")
            val r=exchange("mobile-order?order="+id,JSONObject(),jwt)
            val link=r.optString("subscriptionUrl","").ifBlank{null}
            if(link!=null && (URL(link).protocol!="https"||link.any{it.isWhitespace()}))
                throw IllegalStateException("Unsafe VPN link")
            return Order(r.optString("status"),r.optString("deliveryState"),
                link,r.optString("emailState"))
        }
    }
}
