package tracker.plane.adsb

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import java.text.SimpleDateFormat // Adjusted import for broader compatibility
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
import java.util.concurrent.TimeUnit
import kotlin.math.*



class NotificationReceiver : BroadcastReceiver() {
    private lateinit var fusedLocationClient: FusedLocationProviderClient

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
            fusedLocationClient = LocationServices.getFusedLocationProviderClient(context)
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

            return distance <= 2000
        }

        CoroutineScope(Dispatchers.Main).launch {
            val sdf = SimpleDateFormat("YYYY-MM-dd")
            val currentDate = sdf.format(Date())

            val jsonArray = getData(currentDate)
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

                    val planeLat = plane.getJSONObject(planeInfo).getString("lat")
                    val planeLon = plane.getJSONObject(planeInfo).getString("lon")
                    val spottedAt = plane.getJSONObject(planeInfo).getString("spotted_at")

                    if (planeLat != "-" && planeLon != "-" && planeLat != "N/A" && planeLon != "N/A") {
                        val timeFormat = SimpleDateFormat("HH:mm:ss")
                        val spottedTime: Date? = try {
                            val currentDate = Date()
                            val dateString = SimpleDateFormat("yyyy-MM-dd").format(currentDate) + " " + spottedAt
                            val fullFormat = SimpleDateFormat("yyyy-MM-dd HH:mm:ss")
                            fullFormat.parse(dateString)
                        } catch (e: Exception) {
                            null
                        }

                        if (spottedTime != null) {
                            val currentDate = Date()

                            val timeDifferenceInMillis = currentDate.time - spottedTime.time
                            val timeDifferenceInMinutes = TimeUnit.MILLISECONDS.toMinutes(timeDifferenceInMillis)

                            if (checkIfNear(userLat, userLon, planeLat.toDouble(), planeLon.toDouble()) && timeDifferenceInMinutes <= 1) {
                                notificationText += plane.getJSONObject(planeInfo)
                                    .getString("manufacturer") + " " + plane.getJSONObject(planeInfo)
                                    .getString("model") + ", "
                                planeCounter++
                            }
                        }
                    }
                } catch (e: Exception) {
                    notificationText += e.message
                }
            }

            if (planeCounter > 0) {
                val notification: Notification =
                    NotificationCompat.Builder(context, "NOTIFY_CHANNEL")
                        .setContentTitle("$planeCounter Planes Found")
                        .setContentText(notificationText)
                        .setSmallIcon(android.R.drawable.ic_notification_overlay)
                        .setPriority(NotificationCompat.PRIORITY_HIGH)
                        .build()

                notificationManager.notify(1, notification)
            }
        }
    }
}
