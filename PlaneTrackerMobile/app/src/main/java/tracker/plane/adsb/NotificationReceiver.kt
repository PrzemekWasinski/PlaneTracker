package tracker.plane.adsb

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.icu.text.SimpleDateFormat
import android.os.Build
import androidx.core.app.NotificationCompat
import com.google.firebase.database.FirebaseDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import org.json.JSONArray
import org.json.JSONObject
import java.util.Date

class NotificationReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                "NOTIFY_CHANNEL",
                "Reminder Notifications",
                NotificationManager.IMPORTANCE_HIGH
            )
            notificationManager.createNotificationChannel(channel)
        }

        suspend fun getData(path: String): JSONArray {
            val database = FirebaseDatabase.getInstance()
            val reference = database.getReference(path)

            val jsonArray = JSONArray()

            try {
                val snapshot = reference.get().await()

                if (!snapshot.exists()) {
                    return jsonArray
                }

                for (i in snapshot.children) {
                    val key = i.key

                    val altitude = i.child("altitude").value ?: "N/A"
                    val code_mode_s = i.child("code_mode_s").value ?: "N/A"
                    val icao = i.child("icao").value ?: "N/A"
                    val icao_type_code = i.child("icao_type_code").value ?: "N/A"
                    val lat = i.child("lat").value ?: "N/A"
                    val lon = i.child("lon").value ?: "N/A"
                    val manufacturer = i.child("manufacturer").value ?: "N/A"
                    val model = i.child("model").value ?: "N/A"
                    val operator_flag = i.child("operator_flag").value ?: "N/A"
                    val owner = i.child("owner").value ?: "N/A"
                    val registration = i.child("registration").value ?: "N/A"
                    val speed = i.child("speed").value ?: "N/A"
                    val spotted_at = i.child("spotted_at").value ?: "N/A"
                    val track = i.child("track").value ?: "N/A"

                    val planeJson = JSONObject()
                    planeJson.put("altitude", altitude)
                    planeJson.put("code_mode_s", code_mode_s)
                    planeJson.put("icao", icao)
                    planeJson.put("icao_type_code", icao_type_code)
                    planeJson.put("lat", lat)
                    planeJson.put("lon", lon)
                    planeJson.put("manufacturer", manufacturer)
                    planeJson.put("model", model)
                    planeJson.put("operator_flag", operator_flag)
                    planeJson.put("owner", owner)
                    planeJson.put("registration", registration)
                    planeJson.put("speed", speed)
                    planeJson.put("spotted_at", spotted_at)
                    planeJson.put("track", track)

                    val jsonObject = JSONObject()
                    jsonObject.put(key, planeJson)
                    jsonArray.put(jsonObject)
                }
            } catch (error: Exception) {
                error.printStackTrace()
            }

            return jsonArray
        }

        CoroutineScope(Dispatchers.Main).launch {
            val sdf = SimpleDateFormat("YYYY-MM-dd")
            val currentDate = sdf.format(Date())

            val jsonArray = getData(currentDate)
            var notificationText = ""
            var planeCounter = 0

            for (i in 0..jsonArray.length() - 1) {
                val plane = jsonArray.getJSONObject(i)
                val planeInfo = plane.keys().next()
                //notificationText += plane.getJSONObject(planeInfo).getString("manufacturer").toString() + " " + plane.getJSONObject(planeInfo).getString("model").toString() + " "
                planeCounter++
            }

            val notification: Notification = NotificationCompat.Builder(context, "NOTIFY_CHANNEL")
                .setContentTitle("$planeCounter Planes Found")
                .setContentText(notificationText)
                .setSmallIcon(android.R.drawable.ic_notification_overlay)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .build()

            notificationManager.notify(1, notification)
        }
    }
}
