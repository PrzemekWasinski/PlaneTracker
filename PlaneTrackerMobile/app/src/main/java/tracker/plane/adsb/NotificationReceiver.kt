package tracker.plane.adsb

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import androidx.core.app.NotificationCompat
import com.google.firebase.database.FirebaseDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import org.json.JSONArray
import org.json.JSONObject

class NotificationReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        // Create the Notification Channel (Only required for Android 8+)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                "NOTIFY_CHANNEL",
                "Reminder Notifications",
                NotificationManager.IMPORTANCE_HIGH
            )
            notificationManager.createNotificationChannel(channel)
        }

        // Function to fetch data asynchronously
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

        // Create notification asynchronously
        CoroutineScope(Dispatchers.Main).launch {
            val jsonArray = getData("2025-03-04")
            var notificationText = ""
            for (i in 0 until jsonArray.length()) {
                val plane = jsonArray.getJSONObject(i)
                notificationText += plane.toString() + "\n"
            }

            // Now that we have the data, build the notification
            val notification: Notification = NotificationCompat.Builder(context, "NOTIFY_CHANNEL")
                .setContentTitle("Planes found")
                .setContentText(notificationText)
                .setSmallIcon(android.R.drawable.ic_notification_overlay)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .build()

            // Show the Notification
            notificationManager.notify(1, notification)
        }
    }
}
