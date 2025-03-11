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
                    val icao = i.key

                    val altitude = i.child("altitude").value ?: "N/A"
                    val lat = i.child("lat").value ?: "N/A"
                    val lon = i.child("lon").value ?: "N/A"
                    val speed = i.child("speed").value ?: "N/A"
                    val track = i.child("track").value ?: "N/A"

                    val planeJson = JSONObject()
                    planeJson.put("icao", icao)
                    planeJson.put("altitude", altitude)
                    planeJson.put("lat", lat)
                    planeJson.put("lon", lon)
                    planeJson.put("speed", speed)
                    planeJson.put("track", track)

                    val jsonObject = JSONObject()
                    jsonObject.put(icao, planeJson)
                    jsonArray.put(jsonObject)
                }
            } catch (error: Exception) {
                error.printStackTrace()
            }

            return jsonArray
        }

        CoroutineScope(Dispatchers.Main).launch {
            val sdf = SimpleDateFormat("yyyy-mm-dd")
            val currentDate = sdf.format(Date())
            val lastDate = "2025-03-04"

            val jsonArray = getData(lastDate)
            var notificationText = ""
            var planeCounter = 0

            for (i in 0..jsonArray.length() - 1) {
                val plane = jsonArray.getJSONObject(i)
                val icao = plane.keys().next()
                notificationText += "$icao "
                planeCounter++
            }

            val notification: Notification = NotificationCompat.Builder(context, "NOTIFY_CHANNEL")
                .setContentTitle("$planeCounter planes found")
                .setContentText(notificationText)
                .setSmallIcon(android.R.drawable.ic_notification_overlay)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .build()

            notificationManager.notify(1, notification)
        }
    }
}
