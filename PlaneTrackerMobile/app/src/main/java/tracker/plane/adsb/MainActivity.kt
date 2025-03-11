package tracker.plane.adsb

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.icu.text.SimpleDateFormat
import android.os.Bundle
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.firebase.database.FirebaseDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import org.json.JSONArray
import org.json.JSONObject
import com.google.firebase.database.*
import kotlinx.coroutines.*
import java.util.Date


class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        scheduleNotification()

        val tvMainText = findViewById<TextView>(R.id.tvMain)

        CoroutineScope(Dispatchers.Main).launch {
            val sdf = SimpleDateFormat("yyyy-mm-dd")
            val currentDate = sdf.format(Date())
            val lastDate = "2025-03-04"

            val jsonArray = getData(lastDate)
            var text = ""

            for (i in 0..jsonArray.length() - 1) {
                val plane = jsonArray.getJSONObject(i)
                val icao = plane.keys().next()
                text += "$icao "
            }

            tvMainText.text = text
        }
    }

    private suspend fun getData(path: String): JSONArray {
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

    private fun scheduleNotification() {
        val alarmManager = getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val intent = Intent(this, NotificationReceiver::class.java)
        val pendingIntent = PendingIntent.getBroadcast(
            this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        alarmManager.setRepeating(
            AlarmManager.RTC_WAKEUP,
            System.currentTimeMillis(),
            1 * 60 * 1000,
            pendingIntent
        )
    }
}
