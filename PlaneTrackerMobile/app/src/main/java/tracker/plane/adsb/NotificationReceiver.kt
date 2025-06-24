package tracker.plane.adsb

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import java.text.SimpleDateFormat
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationServices
import com.google.firebase.database.FirebaseDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import org.json.JSONArray
import org.json.JSONObject
import java.util.Date
import android.Manifest
import android.util.Log
import android.widget.Switch
import java.time.LocalTime
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit
import kotlin.math.*

class NotificationReceiver : BroadcastReceiver() {
    private lateinit var fusedLocationClient: FusedLocationProviderClient

    override fun onReceive(context: Context, intent: Intent?) {
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                "NOTIFY_CHANNEL",
                "ADSB Notifications",
                NotificationManager.IMPORTANCE_HIGH
            )
            notificationManager.createNotificationChannel(channel)
        }

        fun checkIfNear(userLat: Double, userLon: Double, targetLat: Double, targetLon: Double): Boolean {
            val earthRadius = 6371000.0

            val userLatRad = Math.toRadians(userLat)
            val userLonRad = Math.toRadians(userLon)
            val targetLatRad = Math.toRadians(targetLat)
            val targetLonRad = Math.toRadians(targetLon)

            val deltaLat = targetLatRad - userLatRad
            val deltaLon = targetLonRad - userLonRad

            //The math was made by chatgpt because i suck at math
            val a = sin(deltaLat / 2).pow(2) + cos(userLatRad) * cos(targetLatRad) * sin(deltaLon / 2).pow(2)
            val c = 2 * atan2(sqrt(a), sqrt(1 - a))

            val distance = earthRadius * c

            return distance <= 8_000 //in meters
        }

        suspend fun getData(path: String): JSONArray {
            val database = FirebaseDatabase.getInstance()
            var reference = database.getReference("device_stats")
            var run = false

            try {
                val stats = reference.get().await()
                run = stats.child("run").value as? Boolean ?: false
            } catch (error: Exception) {
                Log.e("Error", "Error fetching run status")
            }

            fusedLocationClient = LocationServices.getFusedLocationProviderClient(context)
            val jsonArray = JSONArray()

            try {
                if (run) {
                    reference = database.getReference(path)
                    val snapshot = reference.get().await()

                    if (!snapshot.exists()) {
                        return jsonArray
                    }

                    val location = fusedLocationClient.lastLocation.await()
                    val userLat = location.latitude
                    val userLon = location.longitude

                    val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
                    timeFormat.timeZone =
                        TimeZone.getDefault()

                    val now = Date()
                    val recent = 2 * 60 * 1000 //2 min

                    for (i in snapshot.children) {
                        val key = i.key

                        val lat = i.child("lat").value?.toString()
                        val lon = i.child("lon").value?.toString()
                        val spottedAt = i.child("spotted_at").value?.toString()

                        if (lat == null || lon == null || spottedAt == null) continue

                        val isNear = checkIfNear(userLat, userLon, lat.toDouble(), lon.toDouble())

                        val spottedDate: Date? = try {
                            timeFormat.parse(spottedAt)
                        } catch (e: Exception) {
                            null
                        }

                        // Calculate whether time difference is recent
                        val isTimeClose = spottedDate?.let {
                            val nowCal = Calendar.getInstance()
                            val spottedCal = Calendar.getInstance().apply {
                                time = it
                                set(Calendar.YEAR, nowCal.get(Calendar.YEAR))
                                set(Calendar.MONTH, nowCal.get(Calendar.MONTH))
                                set(Calendar.DAY_OF_MONTH, nowCal.get(Calendar.DAY_OF_MONTH))
                            }

                            val diff = kotlin.math.abs(now.time - spottedCal.time.time)
                            diff <= recent
                        } ?: false

                        if (isNear && isTimeClose) {
                            val planeJson = JSONObject().apply {
                                put("altitude", i.child("altitude").value ?: "N/A")
                                put("code_mode_s", i.child("code_mode_s").value ?: "N/A")
                                put("icao", i.child("icao").value ?: "N/A")
                                put("icao_type_code", i.child("icao_type_code").value ?: "N/A")
                                put("lat", lat)
                                put("lon", lon)
                                put("manufacturer", i.child("manufacturer").value ?: "N/A")
                                put("model", i.child("model").value ?: "N/A")
                                put("operator_flag", i.child("operator_flag").value ?: "N/A")
                                put("owner", i.child("owner").value ?: "N/A")
                                put("registration", i.child("registration").value ?: "N/A")
                                put("speed", i.child("speed").value ?: "N/A")
                                put("spotted_at", spottedAt)
                                put("track", i.child("track").value ?: "N/A")
                            }

                            val jsonObject = JSONObject()
                            jsonObject.put(key, planeJson)
                            jsonArray.put(jsonObject)
                        }
                    }
                }
            } catch (error: Exception) {
                error.printStackTrace()
            }

            return jsonArray
        }

        suspend fun getLocation(context: Context): JSONObject {
            val json = JSONObject()
            return try {
                if (ActivityCompat.checkSelfPermission(
                        context,
                        Manifest.permission.ACCESS_FINE_LOCATION
                    ) == android.content.pm.PackageManager.PERMISSION_GRANTED
                ) {
                    val location = fusedLocationClient.lastLocation.await()
                    val latitude = location?.latitude ?: 0.0
                    val longitude = location?.longitude ?: 0.0
                    json.put("lat", latitude)
                    json.put("lon", longitude)
                } else {
                    json.put("lat", 0.0)
                    json.put("lon", 0.0)
                }
                json
            } catch (e: Exception) {
                e.printStackTrace()
                json.put("lat", 0.0)
                json.put("lon", 0.0)
                json
            }
        }

        fun getPath(): String {
            val sdf = SimpleDateFormat("YYYY-MM-dd")
            val currentDate = sdf.format(Date())
            val calendar = Calendar.getInstance()

            val minutes = calendar.get(Calendar.MINUTE)
            val roundedMinutes = (minutes / 10) * 10
            calendar.set(Calendar.MINUTE, roundedMinutes)
            calendar.set(Calendar.SECOND, 0)
            calendar.set(Calendar.MILLISECOND, 0)

            val timeFormat = SimpleDateFormat("HH:mm", Locale.getDefault())
            val roundedTime = timeFormat.format(calendar.time)

            return "/$currentDate/$roundedTime"
        }

        suspend fun getPlanes(): JSONObject {
            val jsonArray = getData(getPath())
            var notificationText = ""
            var planeCounter = 0

            val userLocation = getLocation(context)
            val userLat = userLocation.getDouble("lat")
            val userLon = userLocation.getDouble("lon")
            notificationText = ""

            for (i in 0 until jsonArray.length()) {
                try {
                    val plane = jsonArray.getJSONObject(i)
                    val planeInfo = plane.keys().next()

                    notificationText += plane.getJSONObject(planeInfo)
                        .getString("manufacturer") + " " + plane.getJSONObject(planeInfo)
                        .getString("model") + ", "
                    planeCounter++
                } catch (e: Exception) {
                    notificationText += e.message
                }
            }

            if (userLat == 0.0 || userLon == 0.0) {
                notificationText = "Invalid user coordinates"
                planeCounter++
            }

            if (notificationText.isEmpty()) {
                notificationText = "No planes found"
            }

            val json = JSONObject()

            json.put("count", planeCounter)
            json.put("text", notificationText)
            json.put("lat", userLat)
            json.put("lon", userLon)

            return json
        }

        CoroutineScope(Dispatchers.Main).launch {
            val planeData = getPlanes()

            if (planeData.getInt("count") > 0) {
                val notification: Notification =
                    NotificationCompat.Builder(context, "NOTIFY_CHANNEL")
                        .setContentTitle("${planeData.getString("count")} Planes Found")
                        .setContentText(planeData.getString("text"))
                        .setSmallIcon(R.drawable.ic_plane_notification)
                        .setPriority(NotificationCompat.PRIORITY_MAX)
                        .build()

                notificationManager.notify(1, notification)
            }
        }
    }
}
