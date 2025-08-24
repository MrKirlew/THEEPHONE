package com.kirlewai.adk_mobile_app

import android.Manifest
import android.content.pm.PackageManager
import android.telephony.SmsManager
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity: FlutterActivity() {
    private val CHANNEL = "com.kirlewai.adk_mobile_app/sms"
    private val SMS_PERMISSION_REQUEST = 100

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "sendSMS" -> {
                    val phoneNumber = call.argument<String>("phoneNumber")
                    val message = call.argument<String>("message")
                    
                    if (phoneNumber != null && message != null) {
                        sendSMS(phoneNumber, message, result)
                    } else {
                        result.error("INVALID_ARGUMENTS", "Phone number and message are required", null)
                    }
                }
                "requestSMSPermission" -> {
                    requestSMSPermission(result)
                }
                "hasSMSPermission" -> {
                    result.success(hasSMSPermission())
                }
                else -> {
                    result.notImplemented()
                }
            }
        }
    }

    private fun hasSMSPermission(): Boolean {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestSMSPermission(result: MethodChannel.Result) {
        if (hasSMSPermission()) {
            result.success(true)
        } else {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.SEND_SMS), SMS_PERMISSION_REQUEST)
            // We'll handle the result in onRequestPermissionsResult
            result.success(false)
        }
    }

    private fun sendSMS(phoneNumber: String, message: String, result: MethodChannel.Result) {
        if (!hasSMSPermission()) {
            result.error("NO_PERMISSION", "SMS permission not granted", null)
            return
        }

        try {
            val smsManager = SmsManager.getDefault()
            smsManager.sendTextMessage(phoneNumber, null, message, null, null)
            result.success(true)
        } catch (e: Exception) {
            result.error("SMS_FAILED", "Failed to send SMS: ${e.message}", null)
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        
        if (requestCode == SMS_PERMISSION_REQUEST) {
            // Permission result will be handled by subsequent calls
        }
    }
}