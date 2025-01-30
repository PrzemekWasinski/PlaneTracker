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
import com.google.firebase.FirebaseApp
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.Query
import java.util.Date
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {
    private lateinit var updateReceiver: BroadcastReceiver

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
        FirebaseApp.initializeApp(this)
        scheduleNotification()
        val mainText = findViewById<TextView>(R.id.tvText)

        val getTime = SimpleDateFormat("HH:mm:ss")
        val currentTime = getTime.format(Date())

        val getDate = SimpleDateFormat("dd:MM:yyyy")
        val currentDate = getDate.format(Date()).toString()

        fetchMostRecentTime(currentDate,
            onSuccess = { timeValue ->
                if (timeValue != null) {
                    mainText.text = "Last updated: $timeValue"
                } else {
                    mainText.text = "No update info"
                }
            },
            onFailure = { exception ->
                println("Error fetching data: ${exception.message}")
            }
        )

        updateReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                val updatedText = intent?.getStringExtra("update_text")
                mainText.text = updatedText
            }
        }

        // Register the BroadcastReceiver
        val intentFilter = IntentFilter("com.example.planetracker.UPDATE_VIEW")
        registerReceiver(updateReceiver, intentFilter)
    }

    override fun onDestroy() {
        super.onDestroy()
        // Unregister the BroadcastReceiver
        unregisterReceiver(updateReceiver)
    }

    private fun scheduleNotification() {
        val alarmManager = getSystemService(ALARM_SERVICE) as AlarmManager
        val intent = Intent(this, NotificationReceiver::class.java)
        val pendingIntent = PendingIntent.getBroadcast(
            this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        //set alarm every interval :P
        val interval = TimeUnit.MINUTES.toMillis(120)
        val triggerTime = System.currentTimeMillis() + interval
        alarmManager.setRepeating(AlarmManager.RTC_WAKEUP, triggerTime, interval, pendingIntent)
    }
}