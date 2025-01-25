package com.example.planetracker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.IOException
import android.os.AsyncTask

class NotificationReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        // Call AsyncTask to fetch the plane data and show the notification
        FetchPlanesTask(context).execute()
    }

    // AsyncTask to perform network operations off the main thread
    private class FetchPlanesTask(val context: Context) : AsyncTask<Void, Void, String>() {
        override fun doInBackground(vararg params: Void?): String {
            return getPlanes()
        }

        override fun onPostExecute(result: String?) {
            super.onPostExecute(result)
            if (result != null) {
                // Call the showNotification function after getting the result
                showNotification(context, result)
            }
        }

        private fun getPlanes(): String {
            val client = OkHttpClient()

            val bl_lat = "bottom left latitude"
            val bl_lng = "bottom left longitude"
            val tr_lat = "top right latitude"
            val tr_lng = "top right longitude"
            
            val request = Request.Builder()
                .url("https://flight-radar1.p.rapidapi.com/flights/list-in-boundary?bl_lat=${bl_lat}&bl_lng=${bl_lng}&tr_lat=${tr_lat}&tr_lng=${tr_lng}&limit=300")
                .get()
                .addHeader("x-rapidapi-key", "Rapid API Key")
                .addHeader("x-rapidapi-host", "flight-radar1.p.rapidapi.com")
                .build()

            return try {
                val response = client.newCall(request).execute()

                // Read response content with peekBody
                val responseString = response.peekBody(Long.MAX_VALUE).string()
                if (responseString.isEmpty()) {
                    return "API Error: Response content is empty"
                }

                // Parse the JSON response
                val jsonObject = JSONObject(responseString)
                if (!jsonObject.has("aircraft")) {
                    return "API Error: 'aircraft' key not found in response"
                }

                val planeArray = jsonObject.getJSONArray("aircraft")
                val planeList = mutableListOf<String>()

                for (i in 0 until planeArray.length()) {
                    val planeInfo = planeArray.getJSONArray(i).optString(9, "Unknown")
                    planeList.add(planeInfo)
                }

                planeList.joinToString(" ")
            } catch (e: Exception) {
                // Provide detailed exception info for debugging
                "Error: ${e.localizedMessage ?: "Unknown error"}"
            }
        }

        // Function to show the notification
        private fun showNotification(context: Context, planeString: String) {
            val channelId = "hallo_notification_channel"
            val channelName = "Hallo Notifications"
            val notificationManager =
                context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            // Create a notification channel for Android 8.0+
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                val channel = NotificationChannel(channelId, channelName, NotificationManager.IMPORTANCE_DEFAULT)
                notificationManager.createNotificationChannel(channel)
            }

            // Build the notification
            val notification = NotificationCompat.Builder(context, channelId)
                .setContentTitle("Planes Nearby")
                .setContentText(planeString)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setAutoCancel(true)
                .build()

            // Show the notification
            notificationManager.notify(1, notification)
        }
    }
}
