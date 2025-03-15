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
            val sdf = SimpleDateFormat("YYYY-MM-dd")
            val currentDate = sdf.format(Date())

            val jsonArray = getData(currentDate)
            var text = ""

            for (i in 0..jsonArray.length() - 1) {
                val plane = jsonArray.getJSONObject(i)
                val planeInfo = plane.keys().next()
                text += plane.getJSONObject(planeInfo).getString("manufacturer") + " " + plane.getJSONObject(planeInfo).getString("model") + " "
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
