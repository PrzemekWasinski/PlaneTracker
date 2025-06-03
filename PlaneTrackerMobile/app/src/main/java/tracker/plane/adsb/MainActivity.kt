package tracker.plane.adsb

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.icu.text.SimpleDateFormat
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.DatePicker
import android.widget.Switch
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.firebase.database.FirebaseDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import kotlinx.coroutines.delay
import java.util.*

class MainActivity : AppCompatActivity() {
    private var layoutManager: RecyclerView.LayoutManager? = null
    private lateinit var adapter: RecyclerAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val recyclerView = findViewById<RecyclerView>(R.id.recyclerView)
        val cpuTemp = findViewById<TextView>(R.id.CPUTemp)
        val ramPercentage = findViewById<TextView>(R.id.RAMUsage)
        val runSwitch = findViewById<Switch>(R.id.runSwitch)
        val datePicker = findViewById<DatePicker>(R.id.datePicker)
        val refreshButton = findViewById<Button>(R.id.refreshButton)

        layoutManager = LinearLayoutManager(this)
        recyclerView.layoutManager = layoutManager

        adapter = RecyclerAdapter()
        recyclerView.adapter = adapter

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
            updateRunValue(isChecked)
        }

        refreshButton.setOnClickListener {
            val selectedDate = getDateFromDatePicker(datePicker)
            CoroutineScope(Dispatchers.IO).launch {
                try {
                    val jsonArray = getData(selectedDate, runSwitch)
                    withContext(Dispatchers.Main) {
                        updateRecyclerView(jsonArray)
                    }
                } catch (e: Exception) {
                    Log.e("RefreshError", "Error refreshing data: ${e.message}")
                }
            }
        }

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val sdf = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
                val currentDate = sdf.format(Date())
                val jsonArray = getData(currentDate, runSwitch)
                withContext(Dispatchers.Main) {
                    updateRecyclerView(jsonArray)
                }
            } catch (e: Exception) {
                Log.e("InitialLoadError", "Error loading initial data: ${e.message}")
            }
        }

        scheduleNotification()
    }

    private suspend fun updateDeviceStats(cpuTemp: TextView, ramPercentage: TextView, runSwitch: Switch) {
        try {
            val stats = updateStats()

            val cpuTempValue = stats.optString("cpuTemp", "N/A")
            val ramUsageValue = stats.optString("ramUsage", "N/A")

            cpuTemp.text = "CPU: ${cpuTempValue.substringBefore(".")}°C"
            ramPercentage.text = "RAM: $ramUsageValue%"

            runSwitch.setOnCheckedChangeListener(null)

            runSwitch.isChecked = stats.optBoolean("run", false)

            runSwitch.setOnCheckedChangeListener { _, isChecked ->
                updateRunValue(isChecked)
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

    private suspend fun getData(path: String, runSwitch: Switch): JSONArray {
        val jsonArray = JSONArray()
        if (runSwitch.isChecked) {
            val database = FirebaseDatabase.getInstance()
            val reference = database.getReference(path)
            try {
                val snapshot = reference.get().await()
                if (!snapshot.exists()) return jsonArray

                for (i in snapshot.children) {
                    try {
                        val key = i.key ?: continue

                        val planeJson = JSONObject()
                        planeJson.put("altitude", i.child("altitude").value?.toString() ?: "N/A")
                        planeJson.put(
                            "code_mode_s",
                            i.child("code_mode_s").value?.toString() ?: "N/A"
                        )
                        planeJson.put("icao", i.child("icao").value?.toString() ?: "N/A")
                        planeJson.put(
                            "icao_type_code",
                            i.child("icao_type_code").value?.toString() ?: "N/A"
                        )
                        planeJson.put("lat", i.child("lat").value?.toString() ?: "N/A")
                        planeJson.put("lon", i.child("lon").value?.toString() ?: "N/A")
                        planeJson.put(
                            "manufacturer",
                            i.child("manufacturer").value?.toString() ?: "N/A"
                        )
                        planeJson.put("model", i.child("model").value?.toString() ?: "N/A")
                        planeJson.put(
                            "operator_flag",
                            i.child("operator_flag").value?.toString() ?: "N/A"
                        )
                        planeJson.put("owner", i.child("owner").value?.toString() ?: "N/A")
                        planeJson.put(
                            "registration",
                            i.child("registration").value?.toString() ?: "N/A"
                        )
                        planeJson.put("speed", i.child("speed").value?.toString() ?: "N/A")
                        planeJson.put(
                            "spotted_at",
                            i.child("spotted_at").value?.toString() ?: "N/A"
                        )
                        planeJson.put("track", i.child("track").value?.toString() ?: "N/A")

                        val jsonObject = JSONObject()
                        jsonObject.put(key, planeJson)
                        jsonArray.put(jsonObject)
                    } catch (e: Exception) {
                        Log.e("DataProcessingError", "Error processing plane data: ${e.message}")
                        continue
                    }
                }
            } catch (error: Exception) {
                Log.e("GetDataError", "Error fetching data: ${error.message}")
            }
        }

        return jsonArray
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
                15 * 60 * 1000,
                pendingIntent
            )
        } catch (e: Exception) {
            Log.e("NotificationError", "Failed to schedule notification: ${e.message}")
        }
    }

    private fun updateRunValue(newState: Boolean) {
        try {
            val database = FirebaseDatabase.getInstance()
            val reference = database.getReference("device_stats/run")

            reference.setValue(newState).addOnSuccessListener {
                Log.d("Firebase", "Run value updated to: $newState")
            }.addOnFailureListener {
                Log.e("FirebaseError", "Failed to update run value: ${it.message}")
            }
        } catch (e: Exception) {
            Log.e("UpdateRunError", "Error updating run value: ${e.message}")
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

    private fun updateRecyclerView(jsonArray: JSONArray) {
        try {
            val planeList = mutableListOf<PlaneData>()
            for (i in 0 until jsonArray.length()) {
                try {
                    val planeObj = jsonArray.getJSONObject(i)
                    if (planeObj.keys().hasNext()) {
                        val key = planeObj.keys().next()
                        val planeJson = planeObj.getJSONObject(key)

                        val plane = PlaneData(
                            planeModel = "${planeJson.optString("manufacturer", "Unknown")} ${planeJson.optString("model", "")}",
                            airlineName = planeJson.optString("owner", "Unknown"),
                            registration = planeJson.optString("registration", "Unknown"),
                            spottedAt = "Last seen at: ${planeJson.optString("spotted_at", "Unknown")}"
                        )
                        planeList.add(plane)
                    }
                } catch (e: Exception) {
                    Log.e("PlaneDataError", "Error processing plane at index $i: ${e.message}")
                    continue
                }
            }
            adapter.updateData(planeList)
        } catch (e: Exception) {
            Log.e("RecyclerViewError", "Error updating recycler view: ${e.message}")
        }
    }
}