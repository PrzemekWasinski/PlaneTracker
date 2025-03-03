package com.example.planetracker

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.icu.text.SimpleDateFormat
import android.os.Bundle
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.firebase.FirebaseApp
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.Query
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {
    private var updateReceiver: BroadcastReceiver? = null
    private var adapter: PlaneAdapter? = null
    private var planes = mutableListOf<String>()

    private fun fetchPlaneModelsFromFirestore(collectionName: String) {
        val db = FirebaseFirestore.getInstance()

        db.collection(collectionName)
            .get()
            .addOnSuccessListener { result ->
                planes.clear()
                for (document in result) {
                    val model = document.getString("Model")
                    val registration = document.getString("Registration")
                    val timeSpotted = document.getString("Time")
                    val planeData = "Model = ${model} | Registration = ${registration} Time Spotted: ${timeSpotted}"
                    if (model != null) {
                        planes.add(planeData)
                    }
                }
                adapter?.notifyDataSetChanged()
            }
            .addOnFailureListener { exception ->
                Log.e("Firestore", "Error fetching data", exception)
            }
    }

    private fun fetchMostRecentTime(collectionName: String, onSuccess: (String?) -> Unit, onFailure: (Exception) -> Unit) {
        val db = FirebaseFirestore.getInstance()

        db.collection(collectionName)
            .orderBy("Time", Query.Direction.DESCENDING)
            .limit(1)
            .get()
            .addOnSuccessListener { result ->
                val timeValue = result.documents.firstOrNull()?.get("Time")?.toString()
                onSuccess(timeValue)
            }
            .addOnFailureListener { exception ->
                Log.e("Firestore", "Error fetching most recent document", exception)
                onFailure(exception)
            }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val recyclerView: RecyclerView = findViewById(R.id.rvPlanes)
        recyclerView.layoutManager = LinearLayoutManager(this)
        adapter = PlaneAdapter(this, planes)
        recyclerView.adapter = adapter

        FirebaseApp.initializeApp(this)
        scheduleNotification()

        val mainText = findViewById<TextView>(R.id.tvText)

        val getDate = SimpleDateFormat("dd-MM-yyyy", Locale.getDefault())
        val currentDate = getDate.format(Date()).toString()

        fetchMostRecentTime(currentDate,
            onSuccess = { timeValue ->
                mainText.text = if (timeValue != null) {
                    "Last updated: $timeValue"
                } else {
                    "No update info"
                }
            },
            onFailure = { exception ->
                Log.e("Firestore", "Error fetching data: ${exception.message}")
            }
        )

        fetchPlaneModelsFromFirestore(currentDate)

        val sdf = SimpleDateFormat("HH")
        val currentTime = sdf.format(Date()).toInt()

        updateReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                val updatedText = intent?.getStringExtra("update_text")
                if (updatedText != null && currentTime > 7 && currentTime < 18) {
                    mainText.text = updatedText
                }
            }
        }

        val intentFilter = IntentFilter("com.example.planetracker.UPDATE_VIEW")
        registerReceiver(updateReceiver, intentFilter)
    }

    override fun onDestroy() {
        super.onDestroy()
        updateReceiver?.let {
            unregisterReceiver(it)
        }
    }

    private fun scheduleNotification() {
        val alarmManager = getSystemService(ALARM_SERVICE) as AlarmManager
        val intent = Intent(this, NotificationReceiver::class.java)
        val pendingIntent = PendingIntent.getBroadcast(
            this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val interval = TimeUnit.MINUTES.toMillis(1)
        val triggerTime = System.currentTimeMillis() + interval
        alarmManager.setRepeating(AlarmManager.RTC_WAKEUP, triggerTime, interval, pendingIntent)
    }
}
