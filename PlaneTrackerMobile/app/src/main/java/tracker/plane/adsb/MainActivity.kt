package tracker.plane.adsb

import android.annotation.SuppressLint
import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.icu.text.SimpleDateFormat
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.DatePicker
import android.widget.Switch
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.view.View
import com.google.firebase.database.FirebaseDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext
import org.json.JSONObject
import kotlinx.coroutines.delay
import java.util.*

class MainActivity : AppCompatActivity() {
    private var isUserChangingSwitch = false
    private var userChangeTimestamp = 0L

    @SuppressLint("UseSwitchCompatOrMaterialCode")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val pieChart = findViewById<CustomPieChart>(R.id.pieChart)
        val cpuTemp = findViewById<TextView>(R.id.CPUTemp)
        val ramPercentage = findViewById<TextView>(R.id.RAMUsage)
        val runSwitch = findViewById<Switch>(R.id.runSwitch)
        val datePicker = findViewById<DatePicker>(R.id.datePicker)
        val refreshButton = findViewById<Button>(R.id.refreshButton)

        // Stats TextViews
        val totalPlanesText = findViewById<TextView>(R.id.totalPlanesText)
        val topAirlineText = findViewById<TextView>(R.id.topAirlineText)
        val topModelText = findViewById<TextView>(R.id.topModelText)
        val topManufacturerText = findViewById<TextView>(R.id.topManufacturerText)
        val lastUpdatedText = findViewById<TextView>(R.id.lastUpdatedText)

        // No setup needed for custom pie chart

        CoroutineScope(Dispatchers.IO).launch {
            try {
                while (true) {
                    withContext(Dispatchers.Main) {
                        try {
                            updateDeviceStats(cpuTemp, ramPercentage, runSwitch)
                        } catch (e: Exception) {
                            Log.e("UpdateError", "Error updating UI: ${e.message}")
                        }
                    }
                    delay(5000)
                }
            } catch (e: Exception) {
                Log.e("CoroutineError", "Coroutine error: ${e.message}")
            }
        }

        runSwitch.setOnCheckedChangeListener { _, isChecked ->
            isUserChangingSwitch = true
            userChangeTimestamp = System.currentTimeMillis()

            Log.d("SwitchChange", "User changed switch to: $isChecked")
            updateRunValue(isChecked)
        }

        refreshButton.setOnClickListener {
            val selectedDate = getDateFromDatePicker(datePicker)
            CoroutineScope(Dispatchers.IO).launch {
                try {
                    updateStatsDisplay(selectedDate, pieChart, totalPlanesText, topAirlineText,
                        topModelText, topManufacturerText, lastUpdatedText)
                } catch (e: Exception) {
                    Log.e("RefreshError", "Error refreshing data: ${e.message}")
                }
            }
        }

        // Load initial data for today
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val sdf = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
                val currentDate = sdf.format(Date())
                updateStatsDisplay(currentDate, pieChart, totalPlanesText, topAirlineText,
                    topModelText, topManufacturerText, lastUpdatedText)
            } catch (e: Exception) {
                Log.e("InitialLoadError", "Error loading initial data: ${e.message}")
            }
        }
        scheduleNotification()
    }

    private suspend fun updateStatsDisplay(
        date: String,
        pieChart: CustomPieChart,
        totalPlanesText: TextView,
        topAirlineText: TextView,
        topModelText: TextView,
        topManufacturerText: TextView,
        lastUpdatedText: TextView
    ) {
        try {
            val statsData = getStatsData(date)

            withContext(Dispatchers.Main) {
                updatePieChart(pieChart, statsData.optJSONObject("manufacturer_breakdown"))

                totalPlanesText.text = "Total Planes Today: ${statsData.optString("total", "N/A")}"

                // Parse top airline data
                val topAirlineData = statsData.optJSONObject("top_airline")
                if (topAirlineData != null) {
                    val airlineName = topAirlineData.optString("name", "N/A")
                    val airlineCount = topAirlineData.optString("count", "0")
                    topAirlineText.text = "Top Airline: $airlineName ($airlineCount)"
                } else {
                    topAirlineText.text = "Top Airline: N/A"
                }

                // Parse top model data
                val topModelData = statsData.optJSONObject("top_model")
                if (topModelData != null) {
                    val modelName = topModelData.optString("name", "N/A")
                    val modelCount = topModelData.optString("count")
                    topModelText.text = "Top Model: $modelName ($modelCount)"
                } else {
                    topModelText.text = "Top Model: N/A"
                }

                // Parse top manufacturer data
                val topManufacturerData = statsData.optJSONObject("top_manufacturer")
                if (topManufacturerData != null) {
                    val manufacturerName = topManufacturerData.optString("name", "N/A")
                    val manufacturerCount = topManufacturerData.optString("count", "0")
                    topManufacturerText.text = "Top Manufacturer: $manufacturerName ($manufacturerCount)"
                } else {
                    topManufacturerText.text = "Top Manufacturer: N/A"
                }

                lastUpdatedText.text = "Last Updated: ${statsData.optString("last_updated", "N/A")}"
            }
        } catch (e: Exception) {
            Log.e("StatsDisplayError", "Error updating stats display: ${e.message}")
        }
    }

    private suspend fun getStatsData(date: String): JSONObject {
        val database = FirebaseDatabase.getInstance()
        val reference = database.getReference("$date/stats")

        val statsJson = JSONObject()
        try {
            val snapshot = reference.get().await()
            if (snapshot.exists()) {
                // Get manufacturer breakdown
                val manufacturerBreakdown = snapshot.child("manufacturer_breakdown")
                if (manufacturerBreakdown.exists()) {
                    val manufacturerJson = JSONObject()
                    for (child in manufacturerBreakdown.children) {
                        manufacturerJson.put(child.key ?: "", child.value?.toString() ?: "0")
                    }
                    statsJson.put("manufacturer_breakdown", manufacturerJson)
                }

                // Get other stats
                statsJson.put("total", snapshot.child("total").value?.toString() ?: "0")

                // Parse top airline with nested structure
                val topAirlineSnapshot = snapshot.child("top_airline")
                if (topAirlineSnapshot.exists()) {
                    val topAirlineJson = JSONObject()
                    topAirlineJson.put("name", topAirlineSnapshot.child("name").value?.toString() ?: "N/A")
                    topAirlineJson.put("count", topAirlineSnapshot.child("count").value?.toString() ?: "0")
                    statsJson.put("top_airline", topAirlineJson)
                }

                // Parse top model with nested structure
                val topModelSnapshot = snapshot.child("top_model")
                if (topModelSnapshot.exists()) {
                    val topModelJson = JSONObject()
                    topModelJson.put("name", topModelSnapshot.child("name").value?.toString() ?: "N/A")
                    statsJson.put("top_model", topModelJson)
                }

                // Parse top manufacturer with nested structure
                val topManufacturerSnapshot = snapshot.child("top_manufacturer")
                if (topManufacturerSnapshot.exists()) {
                    val topManufacturerJson = JSONObject()
                    topManufacturerJson.put("name", topManufacturerSnapshot.child("name").value?.toString() ?: "N/A")
                    statsJson.put("top_manufacturer", topManufacturerJson)
                }

                statsJson.put("last_updated", snapshot.child("last_updated").value?.toString() ?: "N/A")
            }
        } catch (e: Exception) {
            Log.e("GetStatsError", "Error fetching stats: ${e.message}")
        }

        return statsJson
    }

    private fun updatePieChart(pieChart: CustomPieChart, manufacturerData: JSONObject?) {
        try {
            val manufacturers = mutableMapOf<String, Int>()

            if (manufacturerData != null) {
                val keys = manufacturerData.keys()
                while (keys.hasNext()) {
                    val manufacturer = keys.next()
                    val count = manufacturerData.optInt(manufacturer, 0)
                    if (count > 0) {
                        manufacturers[manufacturer] = count
                    }
                }
            }

            pieChart.setData(manufacturers)

        } catch (e: Exception) {
            Log.e("PieChartError", "Error updating pie chart: ${e.message}")
        }
    }

    private suspend fun updateDeviceStats(cpuTemp: TextView, ramPercentage: TextView, runSwitch: Switch) {
        try {
            val stats = updateStats()

            val cpuTempValue = stats.optString("cpuTemp", "N/A")
            val ramUsageValue = stats.optString("ramUsage", "N/A")

            cpuTemp.text = "CPU: ${cpuTempValue.substringBefore(".")}°C"
            ramPercentage.text = "RAM: $ramUsageValue%"

            // Check if enough time has passed since user change (10 seconds)
            val currentTime = System.currentTimeMillis()
            if (isUserChangingSwitch && (currentTime - userChangeTimestamp) < 10000) {
                Log.d("SwitchUpdate", "Skipping switch update - user recently changed it")
                return
            }

            // Reset the flag after 10 seconds
            if (isUserChangingSwitch && (currentTime - userChangeTimestamp) >= 10000) {
                isUserChangingSwitch = false
                Log.d("SwitchUpdate", "Reset user change flag")
            }

            val firebaseRunValue = stats.optBoolean("run", false)

            // Only update if different and not during user change period
            if (runSwitch.isChecked != firebaseRunValue && !isUserChangingSwitch) {
                Log.d("SwitchUpdate", "Updating switch from Firebase: $firebaseRunValue")
                runSwitch.setOnCheckedChangeListener(null)
                runSwitch.isChecked = firebaseRunValue
                runSwitch.setOnCheckedChangeListener { _, isChecked ->
                    isUserChangingSwitch = true
                    userChangeTimestamp = System.currentTimeMillis()
                    Log.d("SwitchChange", "User changed switch to: $isChecked")
                    updateRunValue(isChecked)
                }
            }
        } catch (e: Exception) {
            Log.e("DeviceStatsError", "Error in updateDeviceStats: ${e.message}")
        }
    }

    private suspend fun updateStats(): JSONObject {
        val database = FirebaseDatabase.getInstance()
        val reference = database.getReference("device_stats")

        val json = JSONObject()
        try {
            val stats = reference.get().await()

            val cpuTemp = stats.child("cpu_temp").value?.toString() ?: "N/A"
            val ramUsage = stats.child("ram_percentage").value?.toString() ?: "N/A"
            val run = stats.child("run").value as? Boolean ?: false

            json.put("cpuTemp", cpuTemp)
            json.put("ramUsage", ramUsage)
            json.put("run", run)

        } catch (error: Exception) {
            Log.e("UpdateStatsError", "Error fetching stats: ${error.message}")
            json.put("cpuTemp", "N/A")
            json.put("ramUsage", "N/A")
            json.put("run", false)
        }
        return json
    }

    private fun scheduleNotification() {
        try {
            val alarmManager = getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val intent = Intent(this, NotificationReceiver::class.java)
            val pendingIntent = PendingIntent.getBroadcast(
                this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            alarmManager.setRepeating(
                AlarmManager.RTC_WAKEUP,
                System.currentTimeMillis(),
                10 * 60 * 1000,
                pendingIntent
            )
        } catch (e: Exception) {
            Log.e("NotificationError", "Failed to schedule notification: ${e.message}")
        }
    }

    private fun updateRunValue(newState: Boolean) {
        try {
            Log.d("Firebase", "Attempting to update run value to: $newState")
            val database = FirebaseDatabase.getInstance()
            val reference = database.getReference("device_stats/run")

            reference.setValue(newState).addOnSuccessListener {
                Log.d("Firebase", "Run value successfully updated to: $newState")
                // Reset the flag faster on successful update
                CoroutineScope(Dispatchers.Main).launch {
                    delay(2000) // Wait 2 seconds after successful update
                    isUserChangingSwitch = false
                    Log.d("SwitchUpdate", "Reset user change flag after successful Firebase update")
                }
            }.addOnFailureListener {
                Log.e("FirebaseError", "Failed to update run value: ${it.message}")
                // Reset flag on failure too
                isUserChangingSwitch = false
            }
        } catch (e: Exception) {
            Log.e("UpdateRunError", "Error updating run value: ${e.message}")
            isUserChangingSwitch = false
        }
    }

    private fun getDateFromDatePicker(datePicker: DatePicker): String {
        try {
            val day = datePicker.dayOfMonth
            val month = datePicker.month + 1
            val year = datePicker.year

            return String.format("%04d-%02d-%02d", year, month, day)
        } catch (e: Exception) {
            Log.e("DatePickerError", "Error getting date: ${e.message}")
            val sdf = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
            return sdf.format(Date())
        }
    }
}