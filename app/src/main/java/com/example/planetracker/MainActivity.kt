package com.example.planetracker

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.firebase.FirebaseApp
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {
    private lateinit var updateReceiver: BroadcastReceiver

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        FirebaseApp.initializeApp(this)
        scheduleNotification()

        updateReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                val updatedText = intent?.getStringExtra("update_text")
                findViewById<TextView>(R.id.tvText).text = updatedText
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
        val alarmManager = getSystemService(Context.ALARM_SERVICE) as AlarmManager
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